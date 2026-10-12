from setuptools import setup, find_packages

setup(
    name="konman",
    version="1.0.0",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    install_package_data=True,
    install_requires=[
        "click>=8.0.0",
        "pydantic>=2.0.0",
        "ruamel.yaml>=0.17.0",
    ],
    entry_points={
        "console_scripts": [
            "konman=konman.cli:main",
        ],
    },
)
