"""
Arize Phoenix local setup + OpenInference instrumentation for SafeAgent.
Run this BEFORE starting the backend:  python arize/setup.py
"""

import subprocess
import sys

DEPS = [
    "arize-phoenix>=4.0",
    "openinference-instrumentation-langchain>=0.1",
    "openinference-instrumentation-anthropic>=0.1",
    "opentelemetry-sdk",
    "opentelemetry-exporter-otlp",
]


def install():
    subprocess.check_call([sys.executable, "-m", "pip", "install", *DEPS])


if __name__ == "__main__":
    print("Installing Arize Phoenix + OpenInference deps...")
    install()
    print("\nDone. Start Phoenix UI with:")
    print("  python -m phoenix.server.main serve")
    print("\nPhoenix UI: http://localhost:6006")
    print("OTLP endpoint: http://localhost:6006/v1/traces")
