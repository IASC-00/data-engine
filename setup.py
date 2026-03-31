from setuptools import setup, find_packages

setup(
    name='data-engine',
    version='1.0.0',
    packages=find_packages(),
    install_requires=[
        'click>=8.1',
        'rich>=13.0',
        'httpx>=0.27',
        'python-whois>=0.9',
        'dnspython>=2.6',
        'beautifulsoup4>=4.12',
        'python-dotenv>=1.0',
    ],
    entry_points={
        'console_scripts': [
            'de=cli:cli',
        ],
    },
)
