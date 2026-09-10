output fortigate_public_ip {
  value = aws_instance.fortigate.public_ip
}

output fortigate_instance_id {
  value = aws_instance.fortigate.id
}