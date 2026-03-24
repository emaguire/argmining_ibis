# Use the official Python 3 image as the base image
FROM python:3  

# Create and set the working directory inside the container
RUN mkdir -p /home/amf_noop  
WORKDIR /home/amf_noop  

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
ADD README.md /home/amf_noop/README.md

# Add boot script and ensure it has execution permissions
ADD boot.sh ./  
RUN chmod +x boot.sh  

# Set the Flask application environment variable
ENV FLASK_APP app  

# Expose port 5000 for the application
EXPOSE 5000  

# Define the startup command
ENTRYPOINT ["./boot.sh"]  
