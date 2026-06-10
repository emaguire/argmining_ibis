# Use the official Python 3 image as the base image
FROM python:3.14  

# Create and set the working directory inside the container
RUN mkdir -p /home/argmining_ibis
RUN mkdir -p /home/argmining_ibis/temp
WORKDIR /home/argmining_ibis

# Install RabbitMQ as a broker and Redis as a backend for celery
RUN apt-get update
RUN apt-get install -y rabbitmq-server
RUN apt-get install -y redis-server

# Stop Celery complaining about root user 
# (because docker runs commands inside container as root)
ENV C_FORCE_ROOT=1

# Upgrade pip to the latest version
RUN pip install --upgrade pip  

# Add and install dependencies from requirements.txt
ADD requirements.txt .
RUN pip install -r requirements.txt

# Install Gunicorn, a WSGI HTTP server for running Python applications
RUN pip install gunicorn  

# Copy application files into the container
ADD app app  
# Copy the README.md file into the container
ADD README.md /home/argmining_ibis/README.md

# Add boot script and ensure it has execution permissions
ADD boot.sh ./  
RUN chmod +x boot.sh  

# Add a dev variant boot script and ensure it has execution permissions
# (may want to use it in a docker-compose.dev.yml)
ADD dev_boot.sh ./  
RUN chmod +x dev_boot.sh  

# Set the Flask application environment variable
ENV FLASK_APP=app  

# Expose port 5000 for the application
EXPOSE 5000  

# Define the startup command
ENTRYPOINT ["./boot.sh"]  
