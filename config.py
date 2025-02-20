import os
from decimal import Decimal
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Evrmore node RPC details from .env
RPC_URL = os.getenv("RPC_URL")
RPC_USER = os.getenv("RPC_USER")
RPC_PASS = os.getenv("RPC_PASS")

# Configurable constants with defaults
SATORI_ASSET_NAME = os.getenv("SATORI_ASSET_NAME", "SATORI")
TEST_AIRDROP_AMOUNT = Decimal(os.getenv("TEST_AIRDROP_AMOUNT", "0.1"))
BALANCE_CHECK_BATCH_SIZE = int(os.getenv("BALANCE_CHECK_BATCH_SIZE", "10000"))
TX_PROCESSING_BATCH_SIZE = int(os.getenv("TX_PROCESSING_BATCH_SIZE", "300"))
BALANCE_CHECK_PAUSE_TIME = int(os.getenv("BALANCE_CHECK_PAUSE_TIME", "30"))
TX_PROCESSING_PAUSE_TIME = int(os.getenv("TX_PROCESSING_PAUSE_TIME", "60"))
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "40"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "5"))

# Progress file for persistence
PROGRESS_FILE = "airdrop_progress.json"
