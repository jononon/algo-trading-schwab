import json
import os
import schwab
import ssm
import logging

logger = logging.getLogger()
logger.setLevel("INFO")

def auth_handler(event, lambda_context):
    logger.info(f"Event: {event}")
    logger.info(f"Lambda context: {lambda_context} ")

    # Define the authorization endpoint and required parameters
    client_id = 'YOUR_CLIENT_ID'
    redirect_uri = f"{os.environ['API_URL']}/callback"
    scope = 'readonly'  # Change this to the actual scopes required by your app
    response_type = 'code'

    # Construct the authorization URL
    authorization_url = f"https://api.schwab.com/oauth/authorize?response_type={response_type}&client_id={client_id}&redirect_uri={redirect_uri}&scope={scope}"

    # Redirect the user to the authorization URL
    response = {
        'statusCode': 302,
        'headers': {
            'Location': authorization_url
        },
        'body': json.dumps('Redirecting to authorization page...')
    }

    return response


def callback_handler(event, lambda_context):
    code = event['queryStringParameters']['code']

    token_resp = schwab.get_token(code)

    ssm.put_secret("/algotrading/schwab/refreshtoken", token_resp["refresh_token"])

    # Redirect the user to the authorization URL
    response = {
        'statusCode': 200
    }

    return response
