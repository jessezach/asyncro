from setuptools import setup, find_packages
import sys, os

version = '0.026'

setup(name='asyncro',
      version=version,
      description="Simple parallel runner for robot framework",
      classifiers=[
        'Framework :: Robot Framework',
        'Programming Language :: Python',
        'Topic :: Software Development :: Testing',
      ],
      keywords='robotframework parallel runner',
      author='Jesse Zacharias',
      author_email='iamjess988@gmail.com',
      url='https://github.com/jz-jess/asyncro',
      scripts=[os.path.join('scripts', 'asyncro')],
      license='Apache License 2.0',
      packages=find_packages(),
      include_package_data=True,
      zip_safe=True,
      install_requires=[
          'robotframework',
      ],
      entry_points="""
      # -*- Entry points: -*-
      """,
    )
