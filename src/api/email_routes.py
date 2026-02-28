from flask import Blueprint, request, jsonify
from src.services.email_service import email_service
from src.utils.auth_middleware import require_auth

email_bp = Blueprint('email', __name__)

@require_auth
@email_bp.route('/send-email', methods=['POST'])
def send_email():
    try:
        data = request.get_json()
        to_email = data.get('to_email')
        subject = data.get('subject')
        body = data.get('body')
        email_service.send_email(to_email, subject, body)
        return jsonify({'message': 'Email sent successfully'})
    except Exception as e:
           return jsonify({'message': 'Failed to send email', 'error': str(e)}), 500