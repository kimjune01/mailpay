#!/usr/bin/env bash
set -euo pipefail

# Deploy the envelopay exchange to AWS Lambda.
#
# Prerequisites:
#   - AWS CLI configured with appropriate credentials
#   - Lambda function already created
#
# Environment:
#   LAMBDA_FUNCTION  — Lambda function name (default: envelopay-agent)
#   AWS_REGION       — AWS region (default: us-west-2)

LAMBDA_FUNCTION="${LAMBDA_FUNCTION:-envelopay-agent}"
AWS_REGION="${AWS_REGION:-us-west-2}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="$SCRIPT_DIR/.build"
ZIP_FILE="$BUILD_DIR/lambda.zip"

echo "Packaging $LAMBDA_FUNCTION..."

# Clean build dir
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR/package"

# Install dependencies into package dir
pip install --target "$BUILD_DIR/package" --quiet \
    --platform manylinux2014_x86_64 \
    --implementation cp \
    --python-version 3.12 \
    --only-binary=:all: \
    agentmail \
    solana \
    solders

# Copy exchange package
cp -r "$SCRIPT_DIR/exchange" "$BUILD_DIR/package/exchange"

# Copy Lambda entry point
cp "$SCRIPT_DIR/lambda_function.py" "$BUILD_DIR/package/lambda_function.py"

# Copy demo handler (for backward compat)
cp "$SCRIPT_DIR/demo/webhook_handler.py" "$BUILD_DIR/package/webhook_handler.py"

# Build zip
cd "$BUILD_DIR/package"
zip -r "$ZIP_FILE" . -q -x '*.pyc' '*__pycache__*'

echo "Package: $ZIP_FILE ($(du -h "$ZIP_FILE" | cut -f1))"

# Deploy
echo "Deploying to $LAMBDA_FUNCTION in $AWS_REGION..."
aws lambda update-function-code \
    --function-name "$LAMBDA_FUNCTION" \
    --zip-file "fileb://$ZIP_FILE" \
    --region "$AWS_REGION" \
    --output text \
    --query 'FunctionArn'

echo "Done."
