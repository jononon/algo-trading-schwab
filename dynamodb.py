from decimal import Decimal
import boto3
import os

# Initialize a DynamoDB client
dynamodb = boto3.resource('dynamodb')
table_name = os.environ['PORTFOLIO_TABLE_NAME']
table = dynamodb.Table(table_name)


def store_portfolio(portfolio):
    table.put_item(
       Item=portfolio
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
        return item
    else:
        raise Exception("No portfolio found in dynamodb")


def get_all_portfolios():
    response = table.scan()

    items = response['Items']

    # If the table is large and the scan doesn't retrieve all items in one go, paginate
    while 'LastEvaluatedKey' in response:
        response = table.scan(ExclusiveStartKey=response['LastEvaluatedKey'])
        items.extend(response['Items'])

    if len(items) == 0:
        raise Exception("No portfolios found in dynamodb")

    return items