from setuptools import setup, find_packages

setup(
    name="lexiafrik",
    version="1.1.0",
    description="SDK Python pour l'API LexiAfrik — transcription vocale Wolof",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    author="XEL SOFT AI",
    author_email="contact@xelsoftai.com",
    url="https://github.com/xelsoftai/lexiafrik-python",
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
    keywords=["wolof", "speech-to-text", "transcription", "lexiafrik", "asr"],
)
