# First, specify the base Docker image. Apify provides the following base images
# for their Actors with Playwright pre-installed:
# apify/actor-python-playwright:default
# apify/actor-python-playwright:3.12
FROM apify/actor-python-playwright:3.12

# Copy just requirements.txt first to leverage Docker cache
COPY requirements.txt ./

# Install the packages from requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Next, copy the remaining files and directories with the source code.
# Since we do this after pip install, quick build will be really fast
# for most source file changes.
COPY . ./

# Specify how to run the source code
CMD ["python", "main.py"]
