import boto3

def get_secret(parameter_name):
    # Create an SSM client
    ssm = boto3.client('ssm')

    # Fetch the parameter
    parameter = ssm.get_parameter(Name=parameter_name, WithDecryption=True)
    return parameter['Parameter']['Value']


def put_secret(parameter_name, new_value):
    # Create an SSM client
    ssm = boto3.client('ssm')

    # Update the parameter
    ssm.put_parameter(
        Name=parameter_name,
        Value=new_value,
        Type='SecureString',  # or 'StringList' or 'SecureString'
        Overwrite=True  # Set to True to update an existing parameter
    )