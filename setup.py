from setuptools import setup, find_packages

setup(
    name="lexiafrik",
    version="2.0.0",
    description="SDK Python et ligne de commande pour LexiAfrik : transcription vocale des langues africaines",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    author="XEL SOFT AI",
    author_email="contact@xelsoftai.com",
    url="https://lexiafrik.com",
    project_urls={
        "Documentation": "https://docs.lexiafrik.com",
        "Source": "https://github.com/xelsoft-ai/lexiafrik-python",
        "Contact": "https://lexiafrik.com/contact",
    },
    packages=find_packages(),
    python_requires=">=3.8",
    entry_points={"console_scripts": ["lexiafrik=lexiafrik.cli:main"]},
    install_requires=[
        "httpx>=0.24.0",
    ],
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Topic :: Multimedia :: Sound/Audio :: Speech",
        "Intended Audience :: Developers",
    ],
    keywords=["wolof", "african-languages", "speech-to-text", "transcription", "lexiafrik", "asr"],
)
