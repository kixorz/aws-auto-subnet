import os
import logging
import boto3

from crhelper import CfnResource

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

ec2 = boto3.client("ec2", region_name=os.environ['AWS_REGION'])
helper = CfnResource()


@helper.create
def create(event, context):
    properties = event['ResourceProperties']
    vpc_id = properties['VpcId']
    availability_zones = properties['AvailabilityZones']
    subnets = properties['Subnets']
    route_table_id = properties.get('RouteTableId')
    map_public_ip = properties.get('MapPublicIpOnLaunch', 'false').lower() == 'true'

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
        subnet_response = ec2.create_subnet(
            VpcId=vpc_id,
            AvailabilityZone=az,
            CidrBlock=subnet,
            TagSpecifications=tag_specifications,
        )
        subnet_id = subnet_response['Subnet']['SubnetId']
        subnet_ids.append(subnet_id)
        logger.info("Created subnet %s (%s) in %s", subnet_id, subnet, az)

        if route_table_id:
            ec2.associate_route_table(
                RouteTableId=route_table_id,
                SubnetId=subnet_id,
            )
            logger.info("Associated subnet %s with route table %s", subnet_id, route_table_id)

        if map_public_ip:
            ec2.modify_subnet_attribute(
                SubnetId=subnet_id,
                MapPublicIpOnLaunch={'Value': True},
            )
            logger.info("Enabled MapPublicIpOnLaunch on subnet %s", subnet_id)

    helper.Data["SubnetIds"] = subnet_ids


@helper.delete
def delete(event, context):
    stack_id = event['StackId']
    resource_id = event['LogicalResourceId']
    parent_resource_id = f'{stack_id}/{resource_id}'

    response = ec2.describe_subnets(
        Filters=[{'Name': 'tag:ParentResourceId', 'Values': [parent_resource_id]}]
    )
    subnets = response['Subnets']
    for subnet in subnets:
        subnet_id = subnet['SubnetId']

        # Disassociate any non-main route table associations before deleting
        rt_response = ec2.describe_route_tables(
            Filters=[{'Name': 'association.subnet-id', 'Values': [subnet_id]}]
        )
        for rt in rt_response['RouteTables']:
            for assoc in rt.get('Associations', []):
                if assoc.get('SubnetId') == subnet_id and not assoc.get('Main', False):
                    ec2.disassociate_route_table(
                        AssociationId=assoc['RouteTableAssociationId']
                    )
                    logger.info("Disassociated route table from subnet %s", subnet_id)

        ec2.delete_subnet(SubnetId=subnet_id)
        logger.info("Deleted subnet %s", subnet_id)


handler = helper
