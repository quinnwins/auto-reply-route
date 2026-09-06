from setuptools import setup, find_packages

setup(
    name="auto_reply_route",
    version="0.1.0",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    package_data={"auto_reply_route": ["templates/*.md"]},
    include_package_data=True,
    entry_points={
        "console_scripts": [
            "agy-route = auto_reply_route.cli:main",
            "queue-paster = auto_reply_route.queue_paster:main",
        ],
    },
)
