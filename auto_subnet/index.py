import os
import boto3
ec2 = boto3.client("ec2", region_name=os.environ['AWS_REGION'])

from crhelper import CfnResource
helper = CfnResource()


@helper.create
def create(event, context):
    properties = event['ResourceProperties']
    vpc_id = properties['VpcId']
    availability_zones = properties['AvailabilityZones']
    subnets = properties['Subnets']

    stack_id = event['StackId']
    resource_id = event['LogicalResourceId']
    parent_resource_id = f'{stack_id}/{resource_id}'

    tags = properties.get('Tags', [])
    tags.append({'Key': 'ParentResourceId', 'Value': parent_resource_id})
    tag_specifications = [{'ResourceType': 'subnet', 'Tags': tags}]

    azs_len = len(availability_zones)
    subnets_len = len(subnets)
    if azs_len > subnets_len:
        raise ValueError(f"Not enough Subnets {subnets_len} for AvailabilityZones {azs_len}")

    subnet_ids = []
    for az, subnet in zip(availability_zones, subnets):
        subnet_response = ec2.create_subnet(VpcId=vpc_id, AvailabilityZone=az, CidrBlock=subnet, TagSpecifications=tag_specifications)
        subnet_id = subnet_response['Subnet']['SubnetId']
        subnet_ids.append(subnet_id)

    helper.Data["SubnetIds"] = subnet_ids


@helper.delete
def delete(event, context):
    stack_id = event['StackId']
    resource_id = event['LogicalResourceId']
    parent_resource_id = f'{stack_id}/{resource_id}'

    response = ec2.describe_subnets(Filters=[{'Name': 'tag:ParentResourceId', 'Values': [parent_resource_id]}])
    subnets = response['Subnets']
    for subnet in subnets:
        subnet_id = subnet['SubnetId']
        ec2.delete_subnet(SubnetId=subnet_id)

handler = helper