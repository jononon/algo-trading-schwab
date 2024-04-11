from datetime import datetime, timedelta
import time
import traceback
import logging
import copy
from decimal import Decimal

from schwab import get_price_history, get_accounts, get_orders, cancel_order, get_current_quotes, get_account, place_market_order, get_order
from dynamodb import get_portfolio, store_portfolio

logger = logging.getLogger()
logger.setLevel("INFO")

def create_strategy():
    data = {
        "AGG": get_price_history("AGG"),
        "BIL": get_price_history("BIL"),
        "SOXL": get_price_history("SOXL"),
        "TQQQ": get_price_history("TQQQ"),
        "UPRO": get_price_history("UPRO"),
        "TECL": get_price_history("TECL"),
        "TLT": get_price_history("TLT"),
        "QID": get_price_history("QID"),
        "TBF": get_price_history("TBF"),
    }

    if calculate_cumulative_return(data["AGG"], 60) > calculate_cumulative_return(data["BIL"], 60):
        logger.info("Strategy selected: risk on")
        options = ["SOXL", "TQQQ", "UPRO", "TECL"]
        strengths = [(stock, calculate_relative_strength_index(data[stock], 10)) for stock in options]
        sorted_stocks = sorted(strengths, key=lambda x: x[1])
        top_two_stocks = sorted_stocks[:2]
        logger.info(f"Top two stocks: {top_two_stocks}")
        return [x[0] for x in top_two_stocks]
    else:
        if calculate_cumulative_return(data["TLT"], 20) < calculate_cumulative_return(data["BIL"], 20):
            logger.info("Strategy selected: risk off, rising rates")
            options = ["QID", "TBF"]
            strengths = [(stock, calculate_relative_strength_index(data[stock], 20)) for stock in options]
            sorted_stocks = sorted(strengths, key=lambda x: x[1])
            top_stock = sorted_stocks[0]
            logger.info(f"UUP, {top_stock}")
            return ["UUP", top_stock[0]]
        else:
            logger.info("Strategy selected: risk off, falling rates")
            logger.info("UGL, TMF, BTAL, XLP")
            return ["UGL, TMF, BTAL, XLP"]


def calculate_moving_average(data, days):
    # Sort the data by datetime in descending order
    data.sort(key=lambda x: x['datetime'], reverse=True)

    # Initialize the total
    total = Decimal(0)

    # Iterate over the first 'days' elements
    for i in range(days):
        total += Decimal(data[i]['close'])

    # Calculate and return the average
    return total / days


def calculate_relative_strength_index(data, days):
    # Sort the data by datetime in descending order
    data.sort(key=lambda x: x['datetime'], reverse=True)

    # Calculate daily price changes for the last 'days' days
    price_changes = [Decimal(data[i]['close']) - Decimal(data[i + 1]['close']) for i in range(days)]

    # Separate gains and losses
    gains = [change for change in price_changes if change > 0]
    losses = [-change for change in price_changes if change < 0]

    # Calculate average gain and average loss
    avg_gain = sum(gains) / days if gains else 0
    avg_loss = sum(losses) / days if losses else 0

    # Calculate and return the RS
    relative_strength = avg_gain / avg_loss if avg_loss != 0 else 0

    return 100 - (100 / (1 + relative_strength))


def calculate_cumulative_return(data, days):
    # Sort the data by datetime in descending order
    data.sort(key=lambda x: x['datetime'], reverse=True)

    # Get the closing price for the first day and the 'days'th day
    price_current = Decimal(data[0]['close'])
    price_n_days_ago = Decimal(data[days-1]['close']) if len(data) > days-1 else Decimal(data[-1]['close'])

    # Calculate and return the cumulative return
    return (price_current - price_n_days_ago) / price_n_days_ago


def format_time_schwab(time_obj):
    return time_obj.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'


def cancel_outstanding_orders(account_hash: str):
    logger.info(f"Cancelling outstanding orders in account {account_hash}")

    now = datetime.utcnow()
    past = now - timedelta(days=2)

    from_time = format_time_schwab(past)
    to_time = format_time_schwab(now)

    orders = get_orders(account_hash, from_time, to_time)

    for order in orders:
        if order["cancelable"]:
            cancel_order(account_hash, order["orderId"])
            logger.info(f"Order {order['orderId']} has been canceled")
        else:
            logger.info(f"Order {order['orderId']} is not cancelable")


def get_ask_price(current_quotes, stock):
    if stock not in current_quotes:
        logger.warning(f"{stock} NOT IN FETCHED QUOTES")
    else:
        information = current_quotes[stock]

        if not information["realtime"]:
            logger.warning(f"NOT REALTIME QUOTE FOR {stock}")

        quote = information["quote"]
        return Decimal(quote["askPrice"])


def get_bid_price(current_quotes, stock):
    if stock not in current_quotes:
        logger.warning(f"{stock} NOT IN FETCHED QUOTES")
    else:
        information = current_quotes[stock]

        if not information["realtime"]:
            logger.warning(f"NOT REALTIME QUOTE FOR {stock}")

        quote = information["quote"]
        return Decimal(quote["bidPrice"])


def get_value_of_portfolio(portfolio):
    current_quotes = get_current_quotes(portfolio["positions"].keys())

    total_value = Decimal(portfolio["cash"])

    for symbol, quantity in portfolio["positions"].items():
        total_value += get_bid_price(current_quotes, symbol) * Decimal(quantity)

    return total_value


def allocate_remaining_amount(current_quotes, desired_positions, amount_to_spend: Decimal):
    best_desired_positions = desired_positions
    best_amount_to_spend = amount_to_spend
    for symbol in desired_positions.keys():
        price = get_ask_price(current_quotes, symbol)
        if price < amount_to_spend:
            new_desired_positions = copy.deepcopy(desired_positions)
            new_desired_positions[symbol] += Decimal(1)

            further_desired_positions, further_amount_to_spend = allocate_remaining_amount(current_quotes, new_desired_positions, amount_to_spend - price)

            if further_amount_to_spend < best_amount_to_spend:
                best_desired_positions = further_desired_positions
                best_amount_to_spend = further_amount_to_spend

    return best_desired_positions, best_amount_to_spend


def determine_desired_positions(stocks: list[str], amount_to_spend: Decimal):
    current_quotes = get_current_quotes(stocks)

    desired_positions = {}

    amount_per_stock = amount_to_spend / Decimal(len(stocks))

    amount_spent = Decimal(0.0)
    for symbol in stocks:
        price = get_ask_price(current_quotes, symbol)

        quantity = amount_per_stock // price

        desired_positions[symbol] = quantity
        amount_spent += price * quantity

    logger.info(f"Initial allocation: {desired_positions}")

    best_desired_positions, _ = allocate_remaining_amount(current_quotes, desired_positions, amount_to_spend - amount_spent)

    desired_positions = best_desired_positions

    logger.info(f"After allocating remaining amount: {desired_positions}")

    return desired_positions


def determine_position_changes(current_positions: dict[str, Decimal], desired_positions):
    sell = {}
    buy = {}

    stocks = set(current_positions.keys()) | set(desired_positions.keys())

    for stock in stocks:
        if stock not in desired_positions.keys():
            if current_positions[stock] != Decimal(0.0):
                sell[stock] = current_positions[stock]
        elif stock not in current_positions.keys():
            buy[stock] = desired_positions[stock]
        else:
            quantity_to_buy = desired_positions[stock] - current_positions[stock]
            if quantity_to_buy > Decimal(0):
                buy[stock] = quantity_to_buy
            elif quantity_to_buy < Decimal(0):
                sell[stock] = -quantity_to_buy

    return sell, buy


def get_filled_order_confirmations(account_hash, orders):
    order_confirmations = []

    for symbol, order_id in orders:
        while True:
            logger.info(f"Checking order {order_id} for {symbol}")

            order_details = get_order(account_hash, order_id)

            logger.info(f"Order details: {order_details}")

            if order_details["status"] in ["FILLED", "REJECTED", "CANCELED", "EXPIRED", "REPLACED"]:
                order_confirmations.append((symbol, order_details))
                break
            else:
                time.sleep(1)

    return order_confirmations


def get_excecuted_order_value(order_details):
    value = Decimal(0.0)

    for activity in order_details["orderActivityCollection"]:
        for leg in activity["executionLegs"]:
            value += Decimal(leg["quantity"]) * Decimal(leg["price"])

    return value


def run():
    account_hash = "293B4140772D0B86E322EC9497BBEC6F3203B62AFD5C4B2CF1DC8E10880B5CD0"

    logger.info(f"Starting bot for account {account_hash}")

    desired_stocks = create_strategy()

    logger.info(f"Desired stocks: {desired_stocks}")

    current_portfolio = get_portfolio(account_hash)

    logger.info(f"Current portfolio: {current_portfolio}")

    portfolio_value = get_value_of_portfolio(current_portfolio)

    logger.info(f"Portfolio value: {portfolio_value}")

    cancel_outstanding_orders(account_hash)

    desired_positions = determine_desired_positions(desired_stocks, portfolio_value)

    logger.info(f"Desired positions: {desired_positions}")

    sell_positions, buy_positions = determine_position_changes(current_portfolio["positions"], desired_positions)

    logger.info(f"Selling positions: {sell_positions}")
    logger.info(f"Buying positions: {buy_positions}")

    sell_orders = [(symbol, place_market_order(account_hash, symbol, quantity, "SELL")) for symbol, quantity in sell_positions.items()]

    buy_orders = [(symbol, place_market_order(account_hash, symbol, quantity, "BUY")) for symbol, quantity in buy_positions.items()]

    order_confirmations = get_filled_order_confirmations(account_hash, sell_orders + buy_orders)

    net_cash = Decimal(0.0)
    for symbol, order_details in order_confirmations:
        if order_details["status"] == "FILLED":
            if symbol not in current_portfolio["positions"]:
                current_portfolio["positions"][symbol] = Decimal(0)

            if order_details["orderLegCollection"][0]["instruction"] == "SELL":
                current_portfolio["positions"][symbol] -= order_details["filledQuantity"]
                net_cash += get_excecuted_order_value(order_details)
            else:
                current_portfolio["positions"][symbol] += order_details["filledQuantity"]
                net_cash -= get_excecuted_order_value(order_details)
        else:
            logger.error("TRADE FAILED")

    current_portfolio["cash"] += net_cash

    logger.info(f"New portfolio: {current_portfolio}")

    store_portfolio(account_hash, current_portfolio)


def request_handler(event, lambda_context):
    logger.info(f"Event: {event}")
    logger.info(f"Lambda context: {lambda_context} ")

    try:
        run()

        response = {
            "statusCode": 200,
        }

        return response

    except Exception as e:
        logger.error(traceback.format_exc())

        response = {
            "statusCode": 500,
            "error": e,
            "trace": traceback.format_exc()
        }

        return response
