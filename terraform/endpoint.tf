# --- Function URL (default) ---

resource "aws_lambda_function_url" "mcp_server" {
  count              = var.endpoint_type == "function_url" ? 1 : 0
  function_name      = aws_lambda_alias.live.function_name
  qualifier          = aws_lambda_alias.live.name
  authorization_type = "NONE"
}

# --- API Gateway v2 (HTTP API) ---

resource "aws_apigatewayv2_api" "mcp_server" {
  count         = var.endpoint_type == "api_gateway" ? 1 : 0
  name          = "${var.project_name}-${var.environment}-mcp-api"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "lambda" {
  count                  = var.endpoint_type == "api_gateway" ? 1 : 0
  api_id                 = aws_apigatewayv2_api.mcp_server[0].id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_alias.live.invoke_arn
  integration_method     = "POST"
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "default" {
  count     = var.endpoint_type == "api_gateway" ? 1 : 0
  api_id    = aws_apigatewayv2_api.mcp_server[0].id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.lambda[0].id}"
}

resource "aws_apigatewayv2_stage" "default" {
  count       = var.endpoint_type == "api_gateway" ? 1 : 0
  api_id      = aws_apigatewayv2_api.mcp_server[0].id
  name        = "$default"
  auto_deploy = true
}

resource "aws_lambda_permission" "api_gateway" {
  count         = var.endpoint_type == "api_gateway" ? 1 : 0
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_alias.live.function_name
  qualifier     = aws_lambda_alias.live.name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.mcp_server[0].execution_arn}/*/*"
}

# --- Custom Domain (API Gateway only) ---

data "aws_route53_zone" "domain" {
  count = var.endpoint_type == "api_gateway" && var.custom_domain != "" ? 1 : 0
  name  = join(".", slice(split(".", var.custom_domain), 1, length(split(".", var.custom_domain))))
}

resource "aws_acm_certificate" "api" {
  count             = var.endpoint_type == "api_gateway" && var.custom_domain != "" ? 1 : 0
  domain_name       = var.custom_domain
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "cert_validation" {
  for_each = var.endpoint_type == "api_gateway" && var.custom_domain != "" ? {
    for dvo in aws_acm_certificate.api[0].domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      record = dvo.resource_record_value
      type   = dvo.resource_record_type
    }
  } : {}

  allow_overwrite = true
  name            = each.value.name
  records         = [each.value.record]
  ttl             = 60
  type            = each.value.type
  zone_id         = data.aws_route53_zone.domain[0].zone_id
}

resource "aws_acm_certificate_validation" "api" {
  count                   = var.endpoint_type == "api_gateway" && var.custom_domain != "" ? 1 : 0
  certificate_arn         = aws_acm_certificate.api[0].arn
  validation_record_fqdns = [for record in aws_route53_record.cert_validation : record.fqdn]
}

resource "aws_apigatewayv2_domain_name" "api" {
  count       = var.endpoint_type == "api_gateway" && var.custom_domain != "" ? 1 : 0
  domain_name = var.custom_domain

  domain_name_configuration {
    certificate_arn = aws_acm_certificate_validation.api[0].certificate_arn
    endpoint_type   = "REGIONAL"
    security_policy = "TLS_1_2"
  }
}

resource "aws_apigatewayv2_api_mapping" "api" {
  count       = var.endpoint_type == "api_gateway" && var.custom_domain != "" ? 1 : 0
  api_id      = aws_apigatewayv2_api.mcp_server[0].id
  domain_name = aws_apigatewayv2_domain_name.api[0].id
  stage       = aws_apigatewayv2_stage.default[0].id
}

resource "aws_route53_record" "api" {
  count   = var.endpoint_type == "api_gateway" && var.custom_domain != "" ? 1 : 0
  name    = var.custom_domain
  type    = "A"
  zone_id = data.aws_route53_zone.domain[0].zone_id

  alias {
    name                   = aws_apigatewayv2_domain_name.api[0].domain_name_configuration[0].target_domain_name
    zone_id                = aws_apigatewayv2_domain_name.api[0].domain_name_configuration[0].hosted_zone_id
    evaluate_target_health = false
  }
}
