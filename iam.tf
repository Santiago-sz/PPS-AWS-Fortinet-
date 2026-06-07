# Rol para que el FortiGate lea la infraestructura de AWS (Fabric Connector)
resource "aws_iam_role" "fortigate_role" {
  name = "FortiGateFabricConnectorRole"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      },
    ]
  })
}

# Política de solo lectura para auditoría de cumplimiento y postura
resource "aws_iam_role_policy_attachment" "read_only_attach" {
  role       = aws_iam_role.fortigate_role.name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

resource "aws_iam_instance_profile" "fortigate_profile" {
  name = "FortiGateInstanceProfile"
  role = aws_iam_role.fortigate_role.name
}