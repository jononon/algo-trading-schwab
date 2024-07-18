import concurrent.futures
import copy
import logging
import time
import traceback
from workalendar.usa import UnitedStates
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from polygon import RESTClient

from dynamodb import store_portfolio, get_all_portfolios
from schwab import get_price_history, get_orders, cancel_order, get_current_quotes, place_market_order, get_order, \
    get_account, place_trailing_stop_order
from ssm import get_secret

logger = logging.getLogger()
logger.setLevel("INFO")

client = RESTClient(api_key=get_secret("/algotrading/polygon/apikey"))

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

    if (calculate_cumulative_return("AGG", data, 60) >
            calculate_cumulative_return("BIL", data, 60)):
        logger.info("Strategy selected: risk on")
        options = ["SOXL", "TQQQ", "UPRO", "TECL"]
        strengths = [(stock, calculate_relative_strength_index(stock, data, 10)) for stock in options]
        sorted_stocks = sorted(strengths, key=lambda x: x[1])
        logger.info(f"Stocks sorted by 10 day RSI: {sorted_stocks}")
        bottom_two_stocks = sorted_stocks[:2]
        logger.info(f"Top two stocks: {bottom_two_stocks}")
        return [x[0] for x in bottom_two_stocks]
    else:
        if (calculate_cumulative_return("TLT", data, 20) <
                calculate_cumulative_return("BIL", data, 20)):
            logger.info("Strategy selected: risk off, rising rates")
            options = ["QID", "TBF"]
            strengths = [(stock, calculate_relative_strength_index(stock, data, 20)) for stock in options]
            sorted_stocks = sorted(strengths, key=lambda x: x[1])
            logger.info(f"Stocks sorted by 20 day RSI: {sorted_stocks}")
            bottom_stock = sorted_stocks[0]
            logger.info(f"UUP, {bottom_stock}")
            return ["UUP", bottom_stock[0]]
        else:
            logger.info("Strategy selected: risk off, falling rates")
            logger.info("UGL, TMF, BTAL, XLP")
            return ["UGL", "TMF", "BTAL", "XLP"]


def calculate_moving_average(ticker, data, days):
    ticker_data = data[ticker]

    # Sort the data by datetime in descending order
    ticker_data.sort(key=lambda x: x['datetime'], reverse=True)

    # Initialize the total
    total = Decimal(0)

    # Iterate over the first 'days' elements
    for i in range(days):
        total += Decimal(str(ticker_data[i]['close']))

    # Calculate and return the average
    return total / days


def calculate_relative_strength_index(ticker, data, days):
    ticker_data = data[ticker]

    # Sort the data by datetime in ascending order so the most recent comes last
    ticker_data.sort(key=lambda x: x['datetime'])

    # Calculate daily price changes
    price_changes = [Decimal(str(ticker_data[i + 1]['close'])) - Decimal(str(ticker_data[i]['close'])) for i in range(len(ticker_data) - 1)]

    # Initialize gains and losses
    gains = [max(change, 0) for change in price_changes]
    losses = [abs(min(change, 0)) for change in price_changes]

    # Calculate the average gain and average loss using exponential moving average
    avg_gain = sum(gains[-days:]) / days
    avg_loss = sum(losses[-days:]) / days

    # Calculate the RS and RSI
    rs = avg_gain / avg_loss if avg_loss != 0 else float('inf')  # Avoid division by zero
    rsi = 100 - (100 / (1 + rs))

    return rsi


def calculate_cumulative_return(ticker, overall_data, days):
    dividends = get_dividends(ticker)
    ticker_data = overall_data[ticker]

    # Sort the data by datetime in ascending order
    ticker_data.sort(key=lambda x: x['datetime'], reverse=True)

    print(
        f"Starting date {datetime.fromtimestamp(ticker_data[0]['datetime'] / 1000).date()} ending date {datetime.fromtimestamp(ticker_data[-1]['datetime'] / 1000).date()}")

    # Get the closing price for the first day and the 'days'th day
    price_today = Decimal(str(ticker_data[0]['close']))
    price_n_days_ago = Decimal(str(ticker_data[days - 1]['close'])) if len(ticker_data) > days - 1 else Decimal(
        str(ticker_data[-1]['close']))

    date_today = datetime.fromtimestamp(ticker_data[0]['datetime'] / 1000).date()
    date_n_days_ago = datetime.fromtimestamp(ticker_data[days - 1]['datetime'] / 1000).date()

    # Initialize the number of shares with initial investment
    shares_owned = Decimal('1')  # Assuming initial shares owned

    # Iterate over dividends
    if dividends:
        for dividend in dividends:
            ex_date = dividend['ex_date'].date()
            payment_date = dividend['payment_date'].date()
            # Check if the ex-date is within the required period
            if date_n_days_ago < ex_date <= date_today:
                # Find price at payment date
                pay_price = next((item for item in ticker_data if
                                  datetime.fromtimestamp(item['datetime'] / 1000).date() == payment_date), None)

                if pay_price:
                    pay_price = Decimal(str(pay_price['close']))
                    additional_shares = (shares_owned * Decimal(str(dividend['amount']))) / Decimal(str(pay_price))
                    shares_owned += additional_shares

    # Calculate the final value with reinvested dividends
    final_value = shares_owned * price_today
    cumulative_return = (final_value - price_n_days_ago) / price_n_days_ago

    logger.info(
        f"Cumulative return for {ticker}: {cumulative_return}, Dividends reinvested: {shares_owned - Decimal('1')}")

    # Return the cumulative return
    return cumulative_return


def get_dividends(ticker):
    time.sleep(0.2)  # Polygon rate limit is 5 requests per second

    date_format = "%Y-%m-%d"

    dividends = client.list_dividends(ticker, limit=1000)

    output = []

    for dividend in dividends:
        if dividend.ex_dividend_date is not None and dividend.pay_date is not None:
            output.append({
                'ex_date': datetime.strptime(dividend.ex_dividend_date, date_format),
                'payment_date': datetime.strptime(dividend.pay_date, date_format),
                'amount': Decimal(str(dividend.cash_amount))
            })

    logger.info(output)

    return output


def format_time_schwab(time_obj):
    return time_obj.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'


def cancel_outstanding_orders(account_hash: str):
    logger.info(f"Cancelling outstanding orders in account {account_hash}")

    now = datetime.now(timezone.utc)
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
        return Decimal(str(quote["askPrice"]))


def get_bid_price(current_quotes, stock):
    if stock not in current_quotes:
        logger.warning(f"{stock} NOT IN FETCHED QUOTES")
    else:
        information = current_quotes[stock]

        if not information["realtime"]:
            logger.warning(f"NOT REALTIME QUOTE FOR {stock}")

        quote = information["quote"]
        return Decimal(str(quote["bidPrice"]))

def get_last_price(current_quotes, stock):
    if stock not in current_quotes:
        logger.warning(f"{stock} NOT IN FETCHED QUOTES")
    else:
        information = current_quotes[stock]

        if not information["realtime"]:
            logger.warning(f"NOT REALTIME QUOTE FOR {stock}")

        quote = information["quote"]
        return Decimal(str(quote["lastPrice"]))


def get_value_of_portfolio(portfolio):
    current_quotes = get_current_quotes(portfolio["positions"].keys())

    total_value = Decimal(str(portfolio["cash"]))

    for symbol, quantity in portfolio["positions"].items():
        # use ask price instead of bid price to ensure that we don't arbitrarially sell stocks
        total_value += get_ask_price(current_quotes, symbol) * Decimal(str(quantity))

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

    amount_spent = Decimal(0)
    for symbol in stocks:
        price = get_ask_price(current_quotes, symbol)

        quantity = amount_per_stock // price

        desired_positions[symbol] = quantity
        amount_spent += price * quantity

    logger.info(f"Initial allocation: {desired_positions}")

    # best_desired_positions, _ = allocate_remaining_amount(current_quotes, desired_positions, amount_to_spend - amount_spent)
    #
    # desired_positions = best_desired_positions

    logger.info(f"After allocating remaining amount: {desired_positions}")

    return desired_positions


def determine_position_changes(current_positions: dict[str, Decimal], desired_positions):
    sell = {}
    buy = {}

    non_zero_current_positions = {stock for stock, quantity in current_positions.items() if quantity != Decimal(0)}
    if non_zero_current_positions != desired_positions.keys():

        stocks = set(current_positions.keys()) | set(desired_positions.keys())

        for stock in stocks:
            if stock not in desired_positions.keys():
                if current_positions[stock] != Decimal(0):
                    sell[stock] = current_positions[stock]
            elif stock not in current_positions.keys():
                if desired_positions[stock] != Decimal(0):
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
    value = Decimal(0)

    for activity in order_details["orderActivityCollection"]:
        for leg in activity["executionLegs"]:
            value += Decimal(str(leg["quantity"])) * Decimal(str(leg["price"]))

    return value


def get_n_business_days_ago(n):
    # Get today's date
    today = datetime.today().date()

    # Initialize the work calendar for the United States
    cal = UnitedStates()

    # Counter for business days
    business_days_count = 0

    # Calculate the date by going back day by day, skipping weekends and holidays
    current_date = today
    while business_days_count < n:
        current_date -= timedelta(days=1)
        if cal.is_working_day(current_date):
            business_days_count += 1

    return current_date


def get_day_trades_left(roundtrips):
    trades_left = 3

    lookback_date = get_n_business_days_ago(4)

    for day, trades in roundtrips.items():
        date = datetime.strptime(day, '%Y-%m-%d').date()

        if date >= lookback_date:
            trades_left -= int(trades)

    return trades_left

def set_current_day_roundtrips(current_portfolio, account_info):
    today = datetime.today().date()

    # Serialize today's date to a string
    today_str = today.strftime('%Y-%m-%d')

    if 'roundtrips' not in current_portfolio:
        current_portfolio["roundtrips"] = {}

    current_portfolio["roundtrips"][today_str] = Decimal(str(account_info["securitiesAccount"]["roundTrips"]))

    return current_portfolio


def run_for_portfolio(current_portfolio, desired_stocks):
    account_hash = current_portfolio["accountHash"]

    logger.info(f"Processing account with hash {account_hash}")

    account_info = get_account(account_hash)
    current_portfolio["cash"] = Decimal(str(account_info["securitiesAccount"]["currentBalances"]["availableFunds"]))

    current_positions = {}
    for position in account_info["securitiesAccount"]["positions"]:
        current_positions[position["instrument"]["symbol"]] = Decimal(str(position["longQuantity"]))

    current_portfolio["positions"] = current_positions

    current_portfolio = set_current_day_roundtrips(current_portfolio, account_info)

    logger.info(f"Current portfolio: {current_portfolio}")

    portfolio_value = get_value_of_portfolio(current_portfolio)

    logger.info(f"Portfolio value: {portfolio_value}")

    cancel_outstanding_orders(account_hash)

    desired_positions = determine_desired_positions(desired_stocks, portfolio_value)

    logger.info(f"Desired positions: {desired_positions}")

    sell_positions, buy_positions = determine_position_changes(current_portfolio["positions"], desired_positions)

    logger.info(f"Selling positions: {sell_positions}")
    logger.info(f"Buying positions: {buy_positions}")

    order_confirmations = []

    sell_orders = [(symbol, place_market_order(account_hash, symbol, int(quantity), "SELL")) for symbol, quantity in
                   sell_positions.items()]

    order_confirmations.extend(get_filled_order_confirmations(account_hash, sell_orders))

    buy_orders = [(symbol, place_market_order(account_hash, symbol, int(quantity), "BUY")) for symbol, quantity in
                  buy_positions.items()]

    order_confirmations.extend(get_filled_order_confirmations(account_hash, buy_orders))

    net_cash = Decimal(0)
    for symbol, order_details in order_confirmations:
        if order_details["status"] == "FILLED":
            if symbol not in current_portfolio["positions"]:
                current_portfolio["positions"][symbol] = Decimal(0)

            if order_details["orderLegCollection"][0]["instruction"] == "SELL":
                current_portfolio["positions"][symbol] -= Decimal(str(order_details["filledQuantity"]))
                net_cash += get_excecuted_order_value(order_details)
            else:
                current_portfolio["positions"][symbol] += Decimal(str(order_details["filledQuantity"]))
                net_cash -= get_excecuted_order_value(order_details)
        else:
            logger.error("TRADE FAILED")

    current_portfolio["cash"] += net_cash

    logger.info(f"New portfolio: {current_portfolio}")

    store_portfolio(current_portfolio)

    day_trades_left = get_day_trades_left(current_portfolio["roundtrips"])

    for symbol in current_portfolio["positions"]:
        quantity = current_portfolio["positions"][symbol]

        if int(quantity) > 0 and day_trades_left > 0:
            place_trailing_stop_order(account_hash, symbol, int(quantity), 0.5, "SELL")

            day_trades_left -= 1

def run():
    logger.info(f"Starting bot")

    desired_stocks = create_strategy()

    logger.info(f"Desired stocks: {desired_stocks}")

    portfolios = get_all_portfolios()

    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [executor.submit(run_for_portfolio, portfolio, desired_stocks) for portfolio in portfolios]

        exceptions = []

        for future in concurrent.futures.as_completed(futures):
            try:
                future.result()
            except Exception as exc:
                exceptions.append(exc)
                traceback.print_tb(exc.__traceback__)

    if exceptions:
        raise Exception("Errors occurred in one or more threads")


def cancel_orders():
    logger.info(f"Cancelling all orders")

    portfolios = get_all_portfolios()

    for portfolio in portfolios:

        account_hash = portfolio["accountHash"]

        cancel_outstanding_orders(account_hash)


def update_roundtrips():
    logger.info("Updating roundtrips")

    portfolios = get_all_portfolios()

    for portfolio in portfolios:

        account_hash = portfolio["accountHash"]

        account_info = get_account(account_hash)

        current_portfolio = set_current_day_roundtrips(portfolio, account_info)

        store_portfolio(current_portfolio)


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


def cancel_orders_handler(event, lambda_context):
    logger.info(f"Event: {event}")
    logger.info(f"Lambda context: {lambda_context} ")

    try:
        cancel_orders()

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


def update_roundtrips_handler(event, lambda_context):
    logger.info(f"Event: {event}")
    logger.info(f"Lambda context: {lambda_context} ")

    try:
        update_roundtrips()

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
