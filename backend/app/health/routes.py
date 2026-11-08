from flask import Blueprint, jsonify
from flask.typing import ResponseReturnValue

from app.health.schemas import HealthResponse

health_bp = Blueprint('health', __name__, url_prefix='/api')


@health_bp.route('/health', methods=['GET'])
def health() -> ResponseReturnValue:
    return jsonify(HealthResponse(status='ok').model_dump()), 200
