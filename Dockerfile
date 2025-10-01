# Use an official Python runtime as a parent image
FROM python:3.9-bullseye

# Set the working directory in the container
WORKDIR /app

# Install ffmpeg
RUN apt-get update && apt-get install -y ffmpeg
# Verify ffmpeg installation
RUN which ffmpeg

# Copy the requirements file into the container
COPY requirements.txt .

# Add this line to your Dockerfile, for example, right after installing ffmpeg
COPY cookies.txt /workspace/cookies.txt

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application's code into the container
COPY . .

# Command to run the application
CMD ["python", "bot.py"]
