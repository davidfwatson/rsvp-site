from setuptools import setup, find_packages

setup(
    name="rsvp-site",
    version="0.1",
    packages=find_packages(),
    install_requires=[
        'Flask',
        'pytest',
        'uwsgi',
        'google-auth-oauthlib',
        'google-auth',
        'google-api-python-client',
        'markdown',
        'unidecode'
    ],
)