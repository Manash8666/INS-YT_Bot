"""Auth_Manager for credential encryption and token management."""

import os
from datetime import datetime, timedelta
from typing import Optional
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken

from ..models.core import AccountStatus
from ..models.value_objects import Token, Credentials
from ..storage.storage import Storage
from ..exceptions import (
    BotError, UnauthorizedError, StorageUnavailableError
)


class Auth_Manager:
    """Manages authentication credentials and tokens with Fernet encryption."""

    def __init__(
        self,
        storage: Storage,
        retry,
        logger,
        master_key: Optional[bytes] = None,
    ):
        self.storage = storage
        self.retry = retry
        self.logger = logger

        if master_key is None:
            master_key = self._load_or_generate_master_key()

        self._fernet = Fernet(master_key)

    # ------------------------------------------------------------------
    # Key management
    # ------------------------------------------------------------------

    def _load_or_generate_master_key(self) -> bytes:
        """Load key from BOT_MASTER_KEY env var, or auto-generate + save."""
        raw = os.environ.get("BOT_MASTER_KEY")
        if raw:
            key = raw.encode() if isinstance(raw, str) else raw
            try:
                Fernet(key)          # validate
                return key
            except Exception as exc:
                raise BotError(f"Invalid BOT_MASTER_KEY: {exc}") from exc

        # Auto-generate a key and persist it to .env so it survives restarts
        key = Fernet.generate_key()
        env_path = os.path.join(os.getcwd(), ".env")
        try:
            lines = open(env_path).readlines() if os.path.exists(env_path) else []
            # Remove any existing BOT_MASTER_KEY line
            lines = [l for l in lines if not l.startswith("BOT_MASTER_KEY=")]
            lines.append(f"BOT_MASTER_KEY={key.decode()}\n")
            with open(env_path, "w") as f:
                f.writelines(lines)
        except Exception:
            pass  # non-fatal if we can't write .env

        os.environ["BOT_MASTER_KEY"] = key.decode()
        print("[Auth] Auto-generated BOT_MASTER_KEY and saved to .env")
        return key

    # ------------------------------------------------------------------
    # Encryption helpers
    # ------------------------------------------------------------------

    def _encrypt(self, data: bytes) -> bytes:
        return self._fernet.encrypt(data)

    def _decrypt(self, ciphertext: bytes) -> bytes:
        return self._fernet.decrypt(ciphertext)

    # ------------------------------------------------------------------
    # Credential storage
    # ------------------------------------------------------------------

    def store_credentials(self, account_id: str, credentials: "Credentials") -> None:
        encrypted = self._encrypt(credentials.to_bytes())
        account = self.storage.load_account(account_id)
        self.storage.store_account(
            account_id=account_id,
            platform=account.platform,
            status=account.status,
            encrypted_creds=encrypted,
            encrypted_access_token=account.encrypted_access_token,
            encrypted_refresh_token=account.encrypted_refresh_token,
            token_expires_at=account.token_expires_at,
            created_at=account.created_at,
        )

    def load_credentials(self, account_id: str) -> "Credentials":
        encrypted = self.storage.load_encrypted_creds(account_id)
        try:
            return Credentials.from_bytes(self._decrypt(encrypted))
        except InvalidToken as exc:
            raise StorageUnavailableError(
                f"Failed to decrypt credentials for {account_id}"
            ) from exc

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    def get_token(self, account_id: str) -> Token:
        account = self.storage.load_account(account_id)
        if account.status == AccountStatus.UNAUTHORIZED:
            raise UnauthorizedError(account_id)

        if account.token_expires_at > datetime.utcnow():
            try:
                raw = self._decrypt(account.encrypted_access_token).decode()
                return Token(access_token=raw, expires_at=account.token_expires_at)
            except InvalidToken as exc:
                raise StorageUnavailableError(
                    f"Failed to decrypt token for {account_id}"
                ) from exc

        return self.refresh_token(account_id)

    def refresh_token(self, account_id: str) -> Token:
        from ..retry.retry_handler import RetryProfile, PROFILE_TOKEN_REFRESH

        def _do_refresh():
            credentials = self.load_credentials(account_id)
            new_token = f"refreshed_{uuid4().hex}"
            expires = datetime.utcnow() + timedelta(days=365)
            return Token(
                access_token=new_token,
                expires_at=expires,
                refresh_token=credentials.refresh_token,
            )

        try:
            token = self.retry.execute(
                _do_refresh,
                profile=PROFILE_TOKEN_REFRESH,
                is_transient=lambda e: isinstance(e, (ConnectionError, TimeoutError, OSError)),
                is_permanent=lambda e: isinstance(e, (UnauthorizedError, InvalidToken)),
                context={"account_id": account_id},
            )
            encrypted = self._encrypt(token.access_token.encode())
            self.storage.store_encrypted_token(account_id, encrypted)
            self.storage.update_account_status(account_id, AccountStatus.AUTHORIZED)
            account = self.storage.load_account(account_id)
            self.storage.store_account(
                account_id=account_id,
                platform=account.platform,
                status=account.status,
                encrypted_creds=account.encrypted_credentials,
                encrypted_access_token=encrypted,
                encrypted_refresh_token=account.encrypted_refresh_token,
                token_expires_at=token.expires_at,
                created_at=account.created_at,
            )
            return token
        except (UnauthorizedError, InvalidToken):
            self.storage.update_account_status(account_id, AccountStatus.UNAUTHORIZED)
            raise UnauthorizedError(account_id)
        except Exception:
            self.storage.update_account_status(account_id, AccountStatus.UNAUTHORIZED)
            raise UnauthorizedError(account_id)

    def is_authorized(self, account_id: str) -> bool:
        try:
            account = self.storage.load_account(account_id)
            return account.status == AccountStatus.AUTHORIZED
        except StorageUnavailableError:
            return False
