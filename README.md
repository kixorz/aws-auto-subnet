# AWS Subnet Utilities 🌐

Advanced subnet planning and automated provisioning for AWS CloudFormation.

This project provides a set of **CloudFormation Custom Resources** that simplify complex VPC network design. It exposes powerful subnet calculation logic like VLSM allocation and FLSM splitting, directly within your infrastructure-as-code templates.

### 🚀 Features

*   **AutoSubnet** (`Custom::AutoSubnet`): A specialized provisioner that creates and manages real EC2 Subnets in your VPC using calculated CIDR blocks.
*   **Subnet Info** (`Custom::SubnetInfo`): Retrieve detailed network properties (broadcast, wildcard, usable range) from any CIDR.
*   **Subnet Split** (`Custom::SubnetSplit`): Automatically divide a parent network into equal-sized subnets.
*   **VLSM Allocation** (`Custom::SubnetVLSM`): Optimize address space by allocating subnets based on specific host count requirements.

---

### 🛠 Usage Examples

#### Automatic Split Subnet Provisioning
Actually create EC2 Subnets in a VPC.

```yaml
MySubnetSplit:
  Type: Custom::SubnetSplit
  Properties:
    ServiceToken: !GetAtt SubnetCalculatorFunction.Arn
    Network: "10.0.100.0/16"
    AvailabilityZones:
      Fn::GetAZs: !Ref AWS::Region

MySubnets:
  Type: Custom::AutoSubnet
  Properties:
    ServiceToken: !GetAtt AutoSubnetFunction.Arn
    VpcId: !Ref MyVPC
    Subnets: !GetAtt MySubnetSplit.Subnets
    AvailabilityZones:
      Fn::GetAZs: !Ref AWS::Region
```

#### Explicit Subnet Provisioning
Create explicit EC2 Subnets in a VPC.

```yaml
MySubnets:
  Type: Custom::AutoSubnet
  Properties:
    ServiceToken: !GetAtt AutoSubnetFunction.Arn
    VpcId: !Ref MyVPC
    AvailabilityZones: 
      - !Sub "${AWS::Region}a"
      - !Sub "${AWS::Region}b"
    Subnets:
      - "10.0.1.0/24"
      - "10.0.2.0/24"
```

#### Calculate Subnet Details
Get information about a specific network block.

```yaml
MySubnetInfo:
  Type: Custom::SubnetInfo
  Properties:
    ServiceToken: !GetAtt SubnetCalculatorFunction.Arn
    Network: "10.0.0.0/24"

# Outputs: !GetAtt MySubnetInfo.BroadcastAddress, !GetAtt MySubnetInfo.UsableHosts, etc.
```

#### Split a Network (FLSM)
Divide a large network into multiple equal segments.

```yaml
MySubnetSplit:
  Type: Custom::SubnetSplit
  Properties:
    ServiceToken: !GetAtt SubnetCalculatorFunction.Arn
    Network: "10.0.0.0/16"
    Count: "4"

# Access CIDRs: !GetAtt MySubnetSplit.Subnet1Cidr, !GetAtt MySubnetSplit.Subnet2Cidr, etc.
```

#### Variable-Length Subnet Mask (VLSM)
Allocate subnets sized for specific host requirements (e.g., 100, 50, 25 hosts).

```yaml
MySubnetVLSM:
  Type: Custom::SubnetVLSM
  Properties:
    ServiceToken: !GetAtt SubnetCalculatorFunction.Arn
    Network: "192.168.1.0/24"
    Hosts: "100,50,25"
```

### 📊 Available Attributes

The resources expose the following attributes via `Fn::GetAtt`:

| Resource | Key Attributes |
| :--- | :--- |
| **AutoSubnet** | `SubnetIds` (list of created Subnet IDs) |
| **SubnetInfo** | `NetworkAddress`, `BroadcastAddress`, `FirstUsableHost`, `LastUsableHost`, `SubnetMask`, `PrefixLength`, `TotalAddresses`, `UsableHosts`, `IpClass`, `IsPrivate` |
| **SubnetSplit** | `Subnet{N}Cidr`, `Subnet{N}NetworkAddress`, `Subnet{N}FirstHost`, `Subnet{N}LastHost`, `SubnetCount` |
| **SubnetVLSM** | `Subnet{N}Cidr`, `Subnet{N}UsableHosts`, `WastedAddresses`, `SubnetCount` |

### 📦 Deployment

This project is built with [AWS SAM](https://aws.amazon.com/serverless/sam/).

```bash
sam build
sam deploy --guided
```

---

### 📄 License

This project is licensed under the MIT License.
