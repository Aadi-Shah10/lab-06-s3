#!/usr/bin/env python3
"""
Stage a collection of Project Gutenberg books in a public S3 bucket.

Downloads every book listed in a text file, creates an S3 bucket, makes
its objects publicly readable, and uploads the books together with an
index page so the collection can be browsed at
https://BUCKET.s3.amazonaws.com/index.html.

Usage:
    python stage_books.py book_urls.txt index.html public-mst3k
"""

import json
import logging
import os
import sys
import time

import boto3
import requests
from botocore.exceptions import ClientError

# Set up the logger
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger(__name__)

# One S3 client shared by all functions
s3 = boto3.client("s3", region_name="us-east-1")


def parse_args():
    """Read the book list path, index page path and bucket name from the command line."""
    if len(sys.argv) < 4:
        log.error(f"Usage: {sys.argv[0]} <book_list_file> <index_html> <bucket_name>")
        sys.exit(1)

    list_file, index_path, bucket = sys.argv[1], sys.argv[2], sys.argv[3]
    log.info(f"Book list: {list_file}, index page: {index_path}, bucket: {bucket}")
    return list_file, index_path, bucket


def download_books(list_file, dest_dir):
    """Download each book URL in list_file into dest_dir and return the local paths."""
    os.makedirs(dest_dir, exist_ok=True)

    # Read the URLs, one per line, skipping blank lines
    try:
        with open(list_file) as f:
            urls = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        log.error(f"Book list not found: {list_file}")
        return []

    log.info(f"Found {len(urls)} book URLs in {list_file}")
    paths = []

    for url in urls:
        # Save under the last part of the URL, e.g. books/pg1342.txt
        filename = url.rstrip("/").split("/")[-1]
        path = os.path.join(dest_dir, filename)

        # Skip books already downloaded in a previous run
        if os.path.exists(path):
            log.info(f"Already downloaded, skipping: {path}")
            paths.append(path)
            continue

        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()  # raise an error for 404 etc.
            with open(path, "wb") as f:
                f.write(response.content)
            log.info(f"Downloaded {url} -> {path}")
            paths.append(path)
        except requests.RequestException as e:
            log.error(f"Error downloading {url}: {e}")

        # Be polite to Project Gutenberg's servers
        time.sleep(1)

    log.info(f"{len(paths)} of {len(urls)} books available locally")
    return paths


def create_bucket(bucket):
    """Create the bucket unless it already exists. Return True if it exists afterwards."""
    # Check whether the bucket already exists (e.g. from a previous run)
    try:
        s3.head_bucket(Bucket=bucket)
        log.info(f"Bucket already exists: {bucket}")
        return True
    except ClientError:
        log.info(f"Bucket {bucket} not found, creating it")

    # us-east-1 does not take a LocationConstraint
    try:
        s3.create_bucket(Bucket=bucket)
        log.info(f"Created bucket: {bucket}")
        return True
    except ClientError as e:
        log.error(f"Error creating bucket {bucket}: {e}")
        return False


def make_public(bucket):
    """Turn off Block Public Access and allow anyone to read the bucket's objects."""
    # Public read policy for every object in the bucket
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": "*",
                "Action": "s3:GetObject",
                "Resource": f"arn:aws:s3:::{bucket}/*",
            }
        ],
    }

    try:
        # Block Public Access must be off before the policy can be attached
        s3.put_public_access_block(
            Bucket=bucket,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": False,
                "IgnorePublicAcls": False,
                "BlockPublicPolicy": False,
                "RestrictPublicBuckets": False,
            },
        )
        log.info(f"Turned off Block Public Access for {bucket}")

        s3.put_bucket_policy(Bucket=bucket, Policy=json.dumps(policy))
        log.info(f"Attached public read policy to {bucket}")
        return True
    except ClientError as e:
        log.error(f"Error making bucket {bucket} public: {e}")
        return False


def upload_files(bucket, file_paths):
    """Upload each file to the top level of the bucket. Return the number uploaded."""
    uploaded = 0

    for path in file_paths:
        # Use the file name as the key, e.g. pg1342.txt rather than books/pg1342.txt
        key = os.path.basename(path)
        try:
            s3.upload_file(
                path,
                bucket,
                key,
                ExtraArgs={"ContentType": "text/plain; charset=utf-8"},
            )
            log.info(f"Uploaded {path} -> s3://{bucket}/{key}")
            uploaded += 1
        except FileNotFoundError:
            log.error(f"File not found: {path}")
        except ClientError as e:
            log.error(f"Error uploading {path}: {e}")

    log.info(f"Uploaded {uploaded} of {len(file_paths)} books to {bucket}")
    return uploaded


def upload_index(bucket, index_path):
    """Upload the index page as index.html. Return True on success."""
    try:
        s3.upload_file(
            index_path,
            bucket,
            "index.html",
            ExtraArgs={"ContentType": "text/html"},
        )
        log.info(f"Uploaded {index_path} -> s3://{bucket}/index.html")
        return True
    except FileNotFoundError:
        log.error(f"Index page not found: {index_path}")
        return False
    except ClientError as e:
        log.error(f"Error uploading {index_path}: {e}")
        return False


def main():
    """Download the books, set up a public bucket, and upload everything."""
    list_file, index_path, bucket = parse_args()

    # Download the books
    file_paths = download_books(list_file, "books")
    if not file_paths:
        log.error("No books were downloaded")
        sys.exit(1)

    # Create the bucket and make it publicly readable
    if not create_bucket(bucket):
        sys.exit(1)
    if not make_public(bucket):
        sys.exit(1)

    # Upload the books and the index page
    uploaded = upload_files(bucket, file_paths)
    index_ok = upload_index(bucket, index_path)

    url = f"https://{bucket}.s3.amazonaws.com/index.html"
    if uploaded == len(file_paths) and index_ok:
        log.info(f"Success: {uploaded} books and the index page are online at {url}")
    else:
        log.error(f"Finished with errors: {uploaded} of {len(file_paths)} books uploaded, "
                  f"index page {'uploaded' if index_ok else 'not uploaded'}. URL: {url}")


if __name__ == "__main__":
    main()
