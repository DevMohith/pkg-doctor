from setuptools import setup, find_packages

setup(
    name="agentos-runtime",
    version="0.1.0",
    description="AgentOS Runtime — AI Agent CLI for workplace automation",
    author="Mohith Tummala",
    packages=find_packages(include=["agentos_cli*", "backend*"]),
    python_requires=">=3.10",
    install_requires=[
        "click>=8.0",
        "python-dotenv",
        "requests",
        "litellm>=1.0.0",
        "google-cloud-aiplatform",
        "vertexai",
    ],
    extras_require={
        "windows": ["pywin32"],
    },
    entry_points={
        "console_scripts": [
            "agentos=agentos_cli.main:cli",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3.10",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
    ],
)
