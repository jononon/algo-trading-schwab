from functools import cached_property
import json
import base64
import time
import os
import requests
from ssm import get_secret, put_secret

BASE_URL = "https://api.schwabapi.com"
REDIRECT_URI = 'https://schwab.jonathandamico.me/callback'
REFRESH_TOKEN = None
ACCESS_TOKEN = None
TOKEN_EXPIRY = None


@cached_property
def get_app_key():
    return get_secret("/algotrading/schwab/appkey")


@cached_property
def get_app_secret():
    return get_secret("/algotrading/schwab/appsecret")


def get_token(authorization_code):
    redirect_uri = f"{os.environ['API_URL']}/callback"

    headers = {'Authorization': f'Basic {base64.b64encode(bytes(f"{get_app_key()}:{get_app_secret()}", "utf-8")).decode("utf-8")}', 'Content-Type': 'application/x-www-form-urlencoded'}
    data = {'grant_type': 'authorization_code', 'code': authorization_code, 'redirect_uri': redirect_uri}
    return requests.post('https://api.schwabapi.com/v1/oauth/token', headers=headers, data=data).json()


def get_token_refresh(refresh_token):
    headers = {'Authorization': f'Basic {base64.b64encode(bytes(f"{get_app_key()}:{get_app_secret()}", "utf-8")).decode("utf-8")}',
               'Content-Type': 'application/x-www-form-urlencoded'}
    data = {'grant_type': 'refresh_token', 'refresh_token': refresh_token}
    return requests.post('https://api.schwabapi.com/v1/oauth/token', headers=headers, data=data).json()


def get_access_token():
    global REFRESH_TOKEN, ACCESS_TOKEN, TOKEN_EXPIRY

    if not ACCESS_TOKEN or time.time() > TOKEN_EXPIRY:
        if REFRESH_TOKEN is None:
            REFRESH_TOKEN = get_secret("/algotrading/schwab/refreshtoken")

        token_refresh_response = get_token_refresh(REFRESH_TOKEN)

        ACCESS_TOKEN = token_refresh_response["access_token"]

        REFRESH_TOKEN = token_refresh_response["refresh_token"]
        put_secret("/algotrading/schwab/refreshtoken", token_refresh_response["refresh_token"])

        TOKEN_EXPIRY = time.time() + token_refresh_response['expires_in'] - 60

    return ACCESS_TOKEN


def get_price_history(symbol):
    url = f"{BASE_URL}/marketdata/v1/pricehistory"
    headers = {
        'accept': 'application/json',
        'Authorization': f'Bearer {get_access_token()}'
    }
    params = {
        'symbol': symbol,
        'periodType': 'year',
        'period': '1',
        'frequencyType': 'daily'
    }

    response = requests.get(url, headers=headers, params=params)

    # Ensure the request was successful
    response.raise_for_status()

    # Return the JSON response
    return response.json()["candles"]


def get_current_quotes(symbols: list[str]):
    if len(symbols) == 0:
        return {}

    url = f"{BASE_URL}/marketdata/v1/quotes?symbols={','.join(symbols)}&fields=quote&indicative=false"
    headers = {
        'Authorization': f'Bearer {get_access_token()}'
    }

    response = requests.get(url, headers=headers)

    # Ensure the request was successful
    response.raise_for_status()

    # Return the JSON response
    return response.json()


def get_accounts():
    url = f"{BASE_URL}/trader/v1/accounts"
    headers = {
        'accept': 'application/json',
        'Authorization': f'Bearer {get_access_token()}'
    }

    response = requests.get(url, headers=headers)

    # Ensure the request was successful
    response.raise_for_status()

    # Return the JSON response
    return response.json()


def get_account(account_hash: str):
    url = f"{BASE_URL}/trader/v1/accounts/{account_hash}?fields=positions"
    headers = {
        'Authorization': f'Bearer {get_access_token()}'
    }

    response = requests.get(url, headers=headers)

    # Ensure the request was successful
    response.raise_for_status()

    # Return the JSON response
    return response.json()


def place_limit_order(account_hash: str, symbol: str, quantity: int, limit_price: float, instruction: str):
    url = f"{BASE_URL}/trader/v1/accounts/{account_hash}/orders"
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {get_access_token()}'
    }
    payload = json.dumps({
        "session": "NORMAL",
        "duration": "DAY",
        "orderType": "LIMIT",
        "complexOrderStrategyType": "NONE",
        "quantity": quantity,
        "price": limit_price,
        "orderLegCollection": [
            {
                "orderLegType": "EQUITY",
                "legId": 1,
                "instrument": {
                    "assetType": "EQUITY",
                    "symbol": symbol
                },
                "instruction": instruction,
                "positionEffect": "CLOSING",
                "quantity": quantity
            }
        ],
        "orderStrategyType": "SINGLE",
        "taxLotMethod": "LOSS_HARVESTER"
    })

    response = requests.request("POST", url, headers=headers, data=payload)

    response.raise_for_status()

    location = response.headers.get("Location")
    location_parts = location.split("/")

    return location_parts[-1]


def place_market_order(account_hash: str, symbol: str, quantity: int, instruction: str):
    url = f"{BASE_URL}/trader/v1/accounts/{account_hash}/orders"
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {get_access_token()}'
    }
    payload = json.dumps({
        "session": "NORMAL",
        "duration": "DAY",
        "orderType": "MARKET",
        "complexOrderStrategyType": "NONE",
        "quantity": quantity,
        "orderLegCollection": [
            {
                "orderLegType": "EQUITY",
                "legId": 1,
                "instrument": {
                    "assetType": "EQUITY",
                    "symbol": symbol
                },
                "instruction": instruction,
                "positionEffect": "CLOSING",
                "quantity": quantity
            }
        ],
        "orderStrategyType": "SINGLE",
        "taxLotMethod": "LOSS_HARVESTER"
    })

    response = requests.request("POST", url, headers=headers, data=payload)

    response.raise_for_status()

    location = response.headers.get("Location")
    location_parts = location.split("/")

    return location_parts[-1]


def get_orders(account_hash: str, from_time: str, to_time: str):
    url = f"{BASE_URL}/trader/v1/accounts/{account_hash}/orders?fromEnteredTime={from_time}&toEnteredTime={to_time}"
    headers = {
        'Authorization': f'Bearer {get_access_token()}'
    }

    response = requests.request("GET", url, headers=headers)

    response.raise_for_status()

    return response.json()


def get_order(account_hash: str, order_id: int):
    url = f"{BASE_URL}/trader/v1/accounts/{account_hash}/orders/{order_id}"
    headers = {
        'Authorization': f'Bearer {get_access_token()}'
    }

    response = requests.request("GET", url, headers=headers)

    response.raise_for_status()

    return response.json()


def cancel_order(account_hash: str, order_id: int):
    url = f"{BASE_URL}/trader/v1/accounts/{account_hash}/orders/{order_id}"
    headers = {
        'Authorization': f'Bearer {get_access_token()}'
    }

    response = requests.request("DELETE", url, headers=headers)

    response.raise_for_status()
