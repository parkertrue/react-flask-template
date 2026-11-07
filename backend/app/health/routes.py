from flask import Blueprint, jsonify
from flask.typing import ResponseReturnValue

health_bp = Blueprint('health', __name__, url_prefix='/api')


@health_bp.route('/health', methods=['GET'])
def health() -> ResponseReturnValue:
    return jsonify(status='ok'), 200
