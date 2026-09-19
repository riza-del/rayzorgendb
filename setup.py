from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as f:
    long_description = f.read()

setup(
    name="rayzorgendb",
    version="1.0.0",
    description="Embedded multi-engine database. Zero dependency.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="RayzorgenDB Contributors",
    url="https://github.com/yourname/rayzorgendb",
    license="MIT",
    packages=find_packages(
        exclude=["tests*", "examples*", "rayzorgendb.native*"]
    ),
    python_requires=">=3.8",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Topic :: Database",
    ],
    entry_points={
        "console_scripts": [
            "rayzorgen=rayzorgendb.cli.main:main",
        ],
    },
)
