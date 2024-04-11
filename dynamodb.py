from decimal import Decimal
import boto3
import os

# Initialize a DynamoDB client
dynamodb = boto3.resource('dynamodb')
table_name = os.environ['PORTFOLIO_TABLE_NAME']
table = dynamodb.Table(table_name)

def store_portfolio(account_hash, portfolio):
    # Example: Put an item
    table.put_item(
       Item={
            'accountHash': account_hash,
            'cash': Decimal(portfolio["cash"]),
            'positions': {k: Decimal(v) for k, v in portfolio["positions"].items()}
        }
    )

def get_portfolio(account_hash):
    # Example: Get an item
    response = table.get_item(
        Key={
            'accountHash': account_hash,
        }
    )
    item = response.get('Item', None)

    if item:
        return {
            "cash": float(item["cash"]),
            "positions": {k: float(v) for k, v in item["positions"].items()}
        }
    else:
        raise Exception("No portfolio found in dynamodb")
