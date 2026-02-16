"""
Cloud Storage Integrations

Integration clients for cloud object storage services:
- S3Client: Amazon S3 (via boto3)
- GCSClient: Google Cloud Storage (via google-cloud-storage)
- ADLSClient: Azure Data Lake Storage / Azure Blob Storage (via azure-storage-blob)

Each client provides a uniform interface for:
- Connection testing
- Bucket/container listing
- Object listing and metadata retrieval
- Bucket-level metadata and statistics
"""

import json
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional SDK imports -- handled gracefully so the module can be imported
# even when a particular cloud SDK is not installed.
# ---------------------------------------------------------------------------

try:
    import boto3
    from botocore.exceptions import ClientError as BotoClientError
    HAS_BOTO3 = True
except ImportError:
    boto3 = None  # type: ignore[assignment]
    BotoClientError = Exception  # type: ignore[misc,assignment]
    HAS_BOTO3 = False

try:
    from google.cloud import storage as gcs_storage
    from google.oauth2 import service_account as google_service_account
    HAS_GCS = True
except ImportError:
    gcs_storage = None  # type: ignore[assignment]
    google_service_account = None  # type: ignore[assignment]
    HAS_GCS = False

try:
    from azure.storage.blob import BlobServiceClient as AzureBlobServiceClient
    HAS_AZURE = True
except ImportError:
    AzureBlobServiceClient = None  # type: ignore[assignment]
    HAS_AZURE = False


# ============================================================================
# S3 Client
# ============================================================================

class S3Client:
    """
    Amazon S3 integration client.

    Provides methods to list buckets and objects, retrieve metadata, and
    verify credentials against an AWS account.

    Config keys:
        access_key_id (str): AWS access key ID.
        secret_access_key (str): AWS secret access key.
        region (str): AWS region name (e.g. ``us-east-1``).
        bucket (str, optional): Default bucket to operate on.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialise the S3 client.

        Args:
            config: Dictionary containing ``access_key_id``,
                ``secret_access_key``, ``region``, and optionally ``bucket``.

        Raises:
            ImportError: If ``boto3`` is not installed.
        """
        if not HAS_BOTO3:
            raise ImportError(
                "boto3 is required for the S3 integration. "
                "Install it with: pip install boto3"
            )

        self.config = config
        self.region = config.get("region", "us-east-1")
        self.default_bucket = config.get("bucket")

        self._client = boto3.client(
            "s3",
            aws_access_key_id=config.get("access_key_id"),
            aws_secret_access_key=config.get("secret_access_key"),
            region_name=self.region,
        )
        logger.info("S3Client initialised for region %s", self.region)

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def test_connection(self) -> Tuple[bool, Optional[str]]:
        """
        Verify that the configured AWS credentials can reach S3.

        Returns:
            A tuple of ``(success, message)``.  ``message`` is ``None`` on
            success, or an error description on failure.
        """
        try:
            self._client.list_buckets()
            return True, None
        except Exception as exc:
            logger.error("S3 connection test failed: %s", exc)
            return False, str(exc)

    # ------------------------------------------------------------------
    # Bucket operations
    # ------------------------------------------------------------------

    def list_buckets(self) -> List[Dict[str, Any]]:
        """
        List all S3 buckets accessible with the current credentials.

        Returns:
            A list of dicts, each with keys ``name``, ``created_at``, and
            ``region``.
        """
        try:
            response = self._client.list_buckets()
            buckets: List[Dict[str, Any]] = []

            for b in response.get("Buckets", []):
                bucket_name = b.get("Name", "")
                created_at = b.get("CreationDate")

                # Fetch the bucket's region
                region = self._get_bucket_region(bucket_name)

                buckets.append({
                    "name": bucket_name,
                    "created_at": created_at.isoformat() if isinstance(created_at, datetime) else str(created_at) if created_at else None,
                    "region": region,
                })

            return buckets
        except Exception as exc:
            logger.error("Failed to list S3 buckets: %s", exc)
            return []

    def get_bucket_metadata(self, bucket: str) -> Dict[str, Any]:
        """
        Return bucket-level metadata including approximate size and object
        count.

        This performs a full object listing, which may be slow for very large
        buckets.  For buckets with millions of objects consider using S3
        Inventory instead.

        Args:
            bucket: Name of the S3 bucket.

        Returns:
            A dict with keys ``name``, ``region``, ``total_size_bytes``,
            ``object_count``, ``versioning_enabled``, and ``created_at``.
        """
        metadata: Dict[str, Any] = {
            "name": bucket,
            "region": self._get_bucket_region(bucket),
            "total_size_bytes": 0,
            "object_count": 0,
            "versioning_enabled": False,
            "created_at": None,
        }

        try:
            # Versioning status
            versioning = self._client.get_bucket_versioning(Bucket=bucket)
            metadata["versioning_enabled"] = versioning.get("Status") == "Enabled"
        except Exception as exc:
            logger.warning("Could not retrieve versioning status for bucket %s: %s", bucket, exc)

        try:
            # Aggregate size and count via paginated listing
            paginator = self._client.get_paginator("list_objects_v2")
            total_size = 0
            object_count = 0

            for page in paginator.paginate(Bucket=bucket):
                for obj in page.get("Contents", []):
                    total_size += obj.get("Size", 0)
                    object_count += 1

            metadata["total_size_bytes"] = total_size
            metadata["object_count"] = object_count
        except Exception as exc:
            logger.warning("Could not compute size/count for bucket %s: %s", bucket, exc)

        try:
            # Creation date comes from list_buckets
            response = self._client.list_buckets()
            for b in response.get("Buckets", []):
                if b.get("Name") == bucket:
                    created_at = b.get("CreationDate")
                    metadata["created_at"] = created_at.isoformat() if isinstance(created_at, datetime) else str(created_at) if created_at else None
                    break
        except Exception as exc:
            logger.warning("Could not retrieve creation date for bucket %s: %s", bucket, exc)

        return metadata

    # ------------------------------------------------------------------
    # Object operations
    # ------------------------------------------------------------------

    def list_objects(
        self,
        bucket: str,
        prefix: str = "",
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        List objects in an S3 bucket.

        Args:
            bucket: Name of the S3 bucket.
            prefix: Key prefix to filter objects.
            limit: Maximum number of objects to return.

        Returns:
            A list of dicts with keys ``key``, ``size_bytes``,
            ``last_modified``, ``content_type``, and ``storage_class``.
        """
        try:
            params: Dict[str, Any] = {
                "Bucket": bucket,
                "MaxKeys": limit,
            }
            if prefix:
                params["Prefix"] = prefix

            response = self._client.list_objects_v2(**params)
            objects: List[Dict[str, Any]] = []

            for obj in response.get("Contents", []):
                last_modified = obj.get("LastModified")
                objects.append({
                    "key": obj.get("Key", ""),
                    "size_bytes": obj.get("Size", 0),
                    "last_modified": last_modified.isoformat() if isinstance(last_modified, datetime) else str(last_modified) if last_modified else None,
                    "content_type": None,  # Not available from list; use get_object_metadata
                    "storage_class": obj.get("StorageClass", "STANDARD"),
                })

            return objects
        except Exception as exc:
            logger.error("Failed to list objects in s3://%s/%s: %s", bucket, prefix, exc)
            return []

    def get_object_metadata(self, bucket: str, key: str) -> Dict[str, Any]:
        """
        Retrieve detailed metadata for a single S3 object.

        Args:
            bucket: Name of the S3 bucket.
            key: Full object key.

        Returns:
            A dict with keys ``key``, ``bucket``, ``size_bytes``,
            ``last_modified``, ``content_type``, ``storage_class``,
            ``etag``, ``version_id``, and ``metadata`` (user-defined).
        """
        try:
            response = self._client.head_object(Bucket=bucket, Key=key)
            last_modified = response.get("LastModified")

            return {
                "key": key,
                "bucket": bucket,
                "size_bytes": response.get("ContentLength", 0),
                "last_modified": last_modified.isoformat() if isinstance(last_modified, datetime) else str(last_modified) if last_modified else None,
                "content_type": response.get("ContentType"),
                "storage_class": response.get("StorageClass", "STANDARD"),
                "etag": response.get("ETag"),
                "version_id": response.get("VersionId"),
                "metadata": response.get("Metadata", {}),
            }
        except Exception as exc:
            logger.error("Failed to get metadata for s3://%s/%s: %s", bucket, key, exc)
            return {
                "key": key,
                "bucket": bucket,
                "error": str(exc),
            }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_bucket_region(self, bucket: str) -> Optional[str]:
        """Return the region for *bucket*, or fall back to the configured region."""
        try:
            loc = self._client.get_bucket_location(Bucket=bucket)
            # ``None`` means us-east-1
            return loc.get("LocationConstraint") or "us-east-1"
        except Exception:
            return self.region


# ============================================================================
# GCS Client
# ============================================================================

class GCSClient:
    """
    Google Cloud Storage integration client.

    Provides methods to list buckets and objects, retrieve metadata, and
    verify credentials for a GCP project.

    Config keys:
        project_id (str): GCP project ID.
        credentials (str): Either a JSON string containing service-account
            credentials, or a file path to a JSON key file.
        bucket (str, optional): Default bucket to operate on.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialise the GCS client.

        Args:
            config: Dictionary containing ``project_id``, ``credentials``,
                and optionally ``bucket``.

        Raises:
            ImportError: If ``google-cloud-storage`` is not installed.
        """
        if not HAS_GCS:
            raise ImportError(
                "google-cloud-storage is required for the GCS integration. "
                "Install it with: pip install google-cloud-storage"
            )

        self.config = config
        self.project_id = config.get("project_id")
        self.default_bucket = config.get("bucket")

        credentials = self._resolve_credentials(config.get("credentials"))
        self._client = gcs_storage.Client(
            project=self.project_id,
            credentials=credentials,
        )
        logger.info("GCSClient initialised for project %s", self.project_id)

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def test_connection(self) -> Tuple[bool, Optional[str]]:
        """
        Verify that the configured GCP credentials can reach Cloud Storage.

        Returns:
            A tuple of ``(success, message)``.
        """
        try:
            # Attempt a lightweight API call
            list(self._client.list_buckets(max_results=1))
            return True, None
        except Exception as exc:
            logger.error("GCS connection test failed: %s", exc)
            return False, str(exc)

    # ------------------------------------------------------------------
    # Bucket operations
    # ------------------------------------------------------------------

    def list_buckets(self) -> List[Dict[str, Any]]:
        """
        List all GCS buckets in the configured project.

        Returns:
            A list of dicts with keys ``name``, ``created_at``, and
            ``region``.
        """
        try:
            buckets: List[Dict[str, Any]] = []

            for b in self._client.list_buckets():
                created_at = b.time_created
                buckets.append({
                    "name": b.name,
                    "created_at": created_at.isoformat() if created_at else None,
                    "region": b.location,
                })

            return buckets
        except Exception as exc:
            logger.error("Failed to list GCS buckets: %s", exc)
            return []

    def get_bucket_metadata(self, bucket: str) -> Dict[str, Any]:
        """
        Return bucket-level metadata including approximate size and object
        count.

        Args:
            bucket: Name of the GCS bucket.

        Returns:
            A dict with keys ``name``, ``region``, ``storage_class``,
            ``total_size_bytes``, ``object_count``, ``versioning_enabled``,
            and ``created_at``.
        """
        metadata: Dict[str, Any] = {
            "name": bucket,
            "region": None,
            "storage_class": None,
            "total_size_bytes": 0,
            "object_count": 0,
            "versioning_enabled": False,
            "created_at": None,
        }

        try:
            bkt = self._client.get_bucket(bucket)
            created_at = bkt.time_created

            metadata["region"] = bkt.location
            metadata["storage_class"] = bkt.storage_class
            metadata["versioning_enabled"] = bkt.versioning_enabled or False
            metadata["created_at"] = created_at.isoformat() if created_at else None
        except Exception as exc:
            logger.warning("Could not retrieve bucket info for %s: %s", bucket, exc)

        try:
            total_size = 0
            object_count = 0

            bkt = self._client.get_bucket(bucket)
            for blob in bkt.list_blobs():
                total_size += blob.size or 0
                object_count += 1

            metadata["total_size_bytes"] = total_size
            metadata["object_count"] = object_count
        except Exception as exc:
            logger.warning("Could not compute size/count for bucket %s: %s", bucket, exc)

        return metadata

    # ------------------------------------------------------------------
    # Object operations
    # ------------------------------------------------------------------

    def list_objects(
        self,
        bucket: str,
        prefix: str = "",
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        List objects in a GCS bucket.

        Args:
            bucket: Name of the GCS bucket.
            prefix: Key prefix to filter objects.
            limit: Maximum number of objects to return.

        Returns:
            A list of dicts with keys ``key``, ``size_bytes``,
            ``last_modified``, ``content_type``, and ``storage_class``.
        """
        try:
            bkt = self._client.get_bucket(bucket)
            objects: List[Dict[str, Any]] = []

            for blob in bkt.list_blobs(prefix=prefix or None, max_results=limit):
                updated = blob.updated
                objects.append({
                    "key": blob.name,
                    "size_bytes": blob.size or 0,
                    "last_modified": updated.isoformat() if updated else None,
                    "content_type": blob.content_type,
                    "storage_class": blob.storage_class,
                })

            return objects
        except Exception as exc:
            logger.error("Failed to list objects in gs://%s/%s: %s", bucket, prefix, exc)
            return []

    def get_object_metadata(self, bucket: str, key: str) -> Dict[str, Any]:
        """
        Retrieve detailed metadata for a single GCS object.

        Args:
            bucket: Name of the GCS bucket.
            key: Full object name (key).

        Returns:
            A dict with keys ``key``, ``bucket``, ``size_bytes``,
            ``last_modified``, ``content_type``, ``storage_class``,
            ``etag``, ``generation``, ``crc32c``, ``md5_hash``, and
            ``metadata`` (user-defined).
        """
        try:
            bkt = self._client.get_bucket(bucket)
            blob = bkt.get_blob(key)

            if blob is None:
                return {
                    "key": key,
                    "bucket": bucket,
                    "error": "Object not found",
                }

            updated = blob.updated
            return {
                "key": key,
                "bucket": bucket,
                "size_bytes": blob.size or 0,
                "last_modified": updated.isoformat() if updated else None,
                "content_type": blob.content_type,
                "storage_class": blob.storage_class,
                "etag": blob.etag,
                "generation": blob.generation,
                "crc32c": blob.crc32c,
                "md5_hash": blob.md5_hash,
                "metadata": blob.metadata or {},
            }
        except Exception as exc:
            logger.error("Failed to get metadata for gs://%s/%s: %s", bucket, key, exc)
            return {
                "key": key,
                "bucket": bucket,
                "error": str(exc),
            }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_credentials(creds_value: Optional[str]):
        """
        Resolve *creds_value* to a ``google.oauth2`` credentials object.

        *creds_value* can be:
        - ``None`` -- fall back to Application Default Credentials.
        - A JSON string containing a service-account key.
        - A file path pointing to a JSON key file.
        """
        if not creds_value:
            return None

        # Try parsing as inline JSON first
        try:
            info = json.loads(creds_value)
            return google_service_account.Credentials.from_service_account_info(info)
        except (json.JSONDecodeError, ValueError):
            pass

        # Fall back to treating the value as a file path
        try:
            return google_service_account.Credentials.from_service_account_file(creds_value)
        except Exception as exc:
            logger.warning(
                "Could not load GCS credentials from path '%s': %s. "
                "Falling back to Application Default Credentials.",
                creds_value,
                exc,
            )
            return None


# ============================================================================
# ADLS / Azure Blob Storage Client
# ============================================================================

class ADLSClient:
    """
    Azure Data Lake Storage (Gen2) / Azure Blob Storage integration client.

    Uses the ``azure-storage-blob`` SDK (``BlobServiceClient``) to provide a
    uniform interface for listing containers, blobs, and retrieving metadata.

    Config keys:
        account_name (str): Azure storage account name.
        account_key (str, optional): Storage account access key.
        sas_token (str, optional): Shared Access Signature token.
        container (str, optional): Default container to operate on.

    Authentication priority:
        1. ``account_key`` -- builds a connection string.
        2. ``sas_token`` -- builds a SAS-based account URL.
        3. Neither -- falls back to ``DefaultAzureCredential`` (if
           ``azure-identity`` is installed) or raises.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialise the ADLS / Azure Blob client.

        Args:
            config: Dictionary containing ``account_name`` and one of
                ``account_key`` or ``sas_token``.

        Raises:
            ImportError: If ``azure-storage-blob`` is not installed.
            ValueError: If ``account_name`` is not provided.
        """
        if not HAS_AZURE:
            raise ImportError(
                "azure-storage-blob is required for the ADLS integration. "
                "Install it with: pip install azure-storage-blob"
            )

        self.config = config
        self.account_name = config.get("account_name")
        if not self.account_name:
            raise ValueError("account_name is required for the ADLS integration")

        self.default_container = config.get("container")

        self._service_client = self._build_service_client(config)
        logger.info("ADLSClient initialised for account %s", self.account_name)

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def test_connection(self) -> Tuple[bool, Optional[str]]:
        """
        Verify that the configured Azure credentials can reach Blob Storage.

        Returns:
            A tuple of ``(success, message)``.
        """
        try:
            # A lightweight call that validates credentials
            self._service_client.get_account_information()
            return True, None
        except Exception as exc:
            logger.error("ADLS connection test failed: %s", exc)
            return False, str(exc)

    # ------------------------------------------------------------------
    # Container / bucket operations
    # ------------------------------------------------------------------

    def list_buckets(self) -> List[Dict[str, Any]]:
        """
        List all containers in the storage account.

        The returned dicts use the same shape as the other storage clients
        (``name``, ``created_at``, ``region``).  Azure does not expose a
        per-container region, so ``region`` is always ``None``.

        Returns:
            A list of container dicts.
        """
        try:
            containers: List[Dict[str, Any]] = []

            for c in self._service_client.list_containers():
                last_modified = c.get("last_modified")
                containers.append({
                    "name": c.get("name", ""),
                    "created_at": last_modified.isoformat() if isinstance(last_modified, datetime) else str(last_modified) if last_modified else None,
                    "region": None,  # Not available per-container in Azure
                })

            return containers
        except Exception as exc:
            logger.error("Failed to list Azure containers: %s", exc)
            return []

    def get_bucket_metadata(self, bucket: str) -> Dict[str, Any]:
        """
        Return container-level metadata including approximate total size and
        blob count.

        Args:
            bucket: Name of the Azure Blob container.

        Returns:
            A dict with keys ``name``, ``total_size_bytes``,
            ``object_count``, ``lease_state``, ``lease_status``, and
            ``metadata`` (user-defined container metadata).
        """
        metadata: Dict[str, Any] = {
            "name": bucket,
            "total_size_bytes": 0,
            "object_count": 0,
            "lease_state": None,
            "lease_status": None,
            "metadata": {},
        }

        try:
            container_client = self._service_client.get_container_client(bucket)
            props = container_client.get_container_properties()
            metadata["lease_state"] = props.get("lease", {}).get("state") if isinstance(props.get("lease"), dict) else getattr(props.lease, "state", None) if hasattr(props, "lease") else None
            metadata["lease_status"] = props.get("lease", {}).get("status") if isinstance(props.get("lease"), dict) else getattr(props.lease, "status", None) if hasattr(props, "lease") else None
            metadata["metadata"] = props.get("metadata", {}) if isinstance(props, dict) else getattr(props, "metadata", {})
        except Exception as exc:
            logger.warning("Could not retrieve container properties for %s: %s", bucket, exc)

        try:
            container_client = self._service_client.get_container_client(bucket)
            total_size = 0
            object_count = 0

            for blob in container_client.list_blobs():
                total_size += blob.size or 0
                object_count += 1

            metadata["total_size_bytes"] = total_size
            metadata["object_count"] = object_count
        except Exception as exc:
            logger.warning("Could not compute size/count for container %s: %s", bucket, exc)

        return metadata

    # ------------------------------------------------------------------
    # Object / blob operations
    # ------------------------------------------------------------------

    def list_objects(
        self,
        bucket: str,
        prefix: str = "",
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        List blobs in an Azure Blob container.

        Args:
            bucket: Name of the Azure Blob container.
            prefix: Blob name prefix to filter results.
            limit: Maximum number of blobs to return.

        Returns:
            A list of dicts with keys ``key``, ``size_bytes``,
            ``last_modified``, ``content_type``, and ``storage_class``
            (mapped from the blob's access tier).
        """
        try:
            container_client = self._service_client.get_container_client(bucket)
            objects: List[Dict[str, Any]] = []
            count = 0

            blobs_iter = container_client.list_blobs(name_starts_with=prefix or None)
            for blob in blobs_iter:
                if count >= limit:
                    break
                last_modified = blob.last_modified
                objects.append({
                    "key": blob.name,
                    "size_bytes": blob.size or 0,
                    "last_modified": last_modified.isoformat() if isinstance(last_modified, datetime) else str(last_modified) if last_modified else None,
                    "content_type": blob.content_settings.content_type if blob.content_settings else None,
                    "storage_class": blob.blob_tier,
                })
                count += 1

            return objects
        except Exception as exc:
            logger.error(
                "Failed to list objects in azure://%s/%s: %s",
                bucket, prefix, exc,
            )
            return []

    def get_object_metadata(self, bucket: str, key: str) -> Dict[str, Any]:
        """
        Retrieve detailed metadata for a single Azure blob.

        Args:
            bucket: Name of the Azure Blob container.
            key: Full blob name (key).

        Returns:
            A dict with keys ``key``, ``bucket``, ``size_bytes``,
            ``last_modified``, ``content_type``, ``storage_class``,
            ``etag``, ``content_md5``, ``blob_type``, and ``metadata``
            (user-defined).
        """
        try:
            container_client = self._service_client.get_container_client(bucket)
            blob_client = container_client.get_blob_client(key)
            props = blob_client.get_blob_properties()

            last_modified = props.last_modified
            return {
                "key": key,
                "bucket": bucket,
                "size_bytes": props.size or 0,
                "last_modified": last_modified.isoformat() if isinstance(last_modified, datetime) else str(last_modified) if last_modified else None,
                "content_type": props.content_settings.content_type if props.content_settings else None,
                "storage_class": props.blob_tier,
                "etag": props.etag,
                "content_md5": props.content_settings.content_md5 if props.content_settings else None,
                "blob_type": props.blob_type,
                "metadata": props.metadata or {},
            }
        except Exception as exc:
            logger.error(
                "Failed to get metadata for azure://%s/%s: %s",
                bucket, key, exc,
            )
            return {
                "key": key,
                "bucket": bucket,
                "error": str(exc),
            }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_service_client(config: Dict[str, Any]):
        """
        Construct an ``AzureBlobServiceClient`` from the provided config.

        Tries, in order:
        1. Connection string (account key).
        2. SAS token URL.
        3. ``DefaultAzureCredential`` (requires ``azure-identity``).
        """
        account_name = config.get("account_name")
        account_key = config.get("account_key")
        sas_token = config.get("sas_token")

        if account_key:
            conn_str = (
                f"DefaultEndpointsProtocol=https;"
                f"AccountName={account_name};"
                f"AccountKey={account_key};"
                f"EndpointSuffix=core.windows.net"
            )
            return AzureBlobServiceClient.from_connection_string(conn_str)

        if sas_token:
            account_url = f"https://{account_name}.blob.core.windows.net/?{sas_token}"
            return AzureBlobServiceClient(account_url=account_url)

        # Attempt DefaultAzureCredential as a last resort
        try:
            from azure.identity import DefaultAzureCredential
            credential = DefaultAzureCredential()
            account_url = f"https://{account_name}.blob.core.windows.net"
            return AzureBlobServiceClient(account_url=account_url, credential=credential)
        except ImportError:
            raise ImportError(
                "Neither account_key nor sas_token was provided, and "
                "azure-identity is not installed for DefaultAzureCredential. "
                "Install it with: pip install azure-identity"
            )
