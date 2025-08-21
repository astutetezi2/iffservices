# import configparser
# import logging
#
# from flask import Flask
# from flask_cors import CORS
# from flask_jwt_extended import JWTManager
# from flask_sock import Sock
# from pymongo import MongoClient
# from redis import Redis
#
# logging.basicConfig(level=logging.INFO)
# logger = logging.getLogger(__name__)
#
# # Load config.ini
# config = configparser.ConfigParser()
# config.read('config.ini')
#
#
#
# app.config['JWT_SECRET_KEY'] = config['jwt']['secret_key']
#
# # JWT setup
# jwt = JWTManager(app)
#
# # Redis setup
# redis_client = Redis(
#     host=config['redis']['host'],
#     port=int(config['redis']['port']),
#     db=int(config['redis']['db']),
#     decode_responses=True
# )
#
#
