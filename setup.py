from setuptools import setup


setup(
    name='cldfbench_elcat',
    py_modules=['cldfbench_elcat'],
    include_package_data=True,
    zip_safe=False,
    entry_points={
        'cldfbench.dataset': [
            'elcat=cldfbench_elcat:Dataset',
        ],
        'cldfbench.commands': [
            'elcat=elcat_commands',
        ]
    },
    install_requires=[
        'pycountry',
        'lxml',
        'requests',
        'clldutils',
        'pycldf',
        'cldfbench',
    ],
    extras_require={
        'test': [
            'pytest-cldf',
        ],
    },
)
