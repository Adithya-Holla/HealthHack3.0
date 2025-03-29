from flask import Flask, request, jsonify
from flask_cors import CORS
import os
from ultralytics import YOLO
import uuid
import cloudinary
import cloudinary.uploader
import cloudinary.api
from dotenv import load_dotenv
import tempfile
import shutil
import requests
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

app = Flask(__name__)
CORS(app)

# Create a temporary directory for processing
TEMP_DIR = tempfile.mkdtemp()

# Global model variable
model = None

def load_model():
    try:
        # Configure Cloudinary
        cloudinary.config(
            cloud_name=os.getenv('CLOUDINARY_CLOUD_NAME'),
            api_key=os.getenv('CLOUDINARY_API_KEY'),
            api_secret=os.getenv('CLOUDINARY_API_SECRET')
        )
        
        logger.info("Cloudinary configured successfully")
        
        # Download model from Cloudinary
        model_url = cloudinary.CloudinaryImage("models/best").build_url()
        model_path = os.path.join(TEMP_DIR, 'best.pt')
        
        logger.info(f"Downloading model from: {model_url}")
        
        # Download the model file with timeout and retry
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = requests.get(model_url, timeout=30)
                response.raise_for_status()
                with open(model_path, 'wb') as f:
                    f.write(response.content)
                logger.info(f"Model downloaded successfully to {model_path}")
                break
            except Exception as e:
                logger.error(f"Attempt {attempt + 1} failed: {str(e)}")
                if attempt == max_retries - 1:
                    raise
        
        # Load the model
        logger.info("Loading YOLO model...")
        return YOLO(model_path)
    except Exception as e:
        logger.error(f"Error loading model: {str(e)}")
        raise

@app.before_first_request
def initialize_model():
    global model
    try:
        model = load_model()
        logger.info("Model initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize model: {str(e)}")
        raise

@app.route('/upload', methods=['POST'])
def upload_file():
    try:
        if model is None:
            return jsonify({'error': 'Model not initialized'}), 500
            
        if 'file' not in request.files:
            return jsonify({'error': 'No file part'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No selected file'}), 400
        
        if file:
            # Generate unique filename
            unique_filename = f"{uuid.uuid4()}_{file.filename}"
            
            # Upload original image to Cloudinary
            upload_result = cloudinary.uploader.upload(
                file,
                public_id=f"original_images/{unique_filename}",
                resource_type="auto"
            )
            original_url = upload_result['secure_url']
            
            # Process the image with YOLO
            results = model.predict(original_url)
            
            # Save the processed image temporarily
            processed_filename = f"processed_{unique_filename}"
            processed_path = os.path.join(TEMP_DIR, processed_filename)
            results[0].save(processed_path)
            
            # Upload processed image to Cloudinary
            processed_upload = cloudinary.uploader.upload(
                processed_path,
                public_id=f"processed_images/{processed_filename}",
                resource_type="auto"
            )
            processed_url = processed_upload['secure_url']
            
            # Clean up temporary files
            os.remove(processed_path)
            
            return jsonify({
                'message': 'File uploaded and processed successfully',
                'original_image': original_url,
                'processed_image': processed_url
            })
            
    except Exception as e:
        logger.error(f"Error processing file: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        'status': 'healthy',
        'model_loaded': model is not None
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)