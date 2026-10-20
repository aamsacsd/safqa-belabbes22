# -*- coding: utf-8 -*-
"""Point d'entrée production : gunicorn wsgi:app"""
from app import create_app

app = create_app()
