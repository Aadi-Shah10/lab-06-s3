#!/bin/bash
# Download a Project Gutenberg book, upload it to a private S3 bucket,
# and print a presigned URL that lets anyone read it for a limited time.
set -euo pipefail

# Check that all three arguments were given
if [ "$#" -lt 3 ]; then
    echo "Usage: $0 BOOK_URL BUCKET EXPIRES_SECONDS" >&2
    exit 1
fi

URL="$1"
BUCKET="$2"
EXPIRES="$3"
FILE="$(basename "$URL")"   # e.g. pg1342.txt

# Download the book into books/, keeping the file name from the URL
mkdir -p books
curl -fsSL -o "books/$FILE" "$URL"
echo "Downloaded $URL -> books/$FILE"

# Create the bucket unless it already exists
if aws s3 ls "s3://$BUCKET" > /dev/null 2>&1; then
    echo "Bucket $BUCKET already exists"
else
    aws s3 mb "s3://$BUCKET" --region us-east-1
fi

# Upload the book (the bucket and object stay private)
aws s3 cp "books/$FILE" "s3://$BUCKET/$FILE" --content-type "text/plain; charset=utf-8"

# Presign a temporary URL to the book and print it
aws s3 presign "s3://$BUCKET/$FILE" --expires-in "$EXPIRES"