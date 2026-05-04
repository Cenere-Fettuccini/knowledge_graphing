import os
from neo4j import GraphDatabase
from dotenv import load_dotenv

load_dotenv()

uri = os.getenv("NEO4J_URI", "neo4j://127.0.0.1:7687")
user = os.getenv("NEO4J_USER", "neo4j")
password = os.getenv("NEO4J_PASSWORD", "")

try:
    print(f"Connecting to {uri} as {user}...")
    driver = GraphDatabase.driver(uri, auth=(user, password))
    driver.verify_connectivity()
    print("Success! Neo4j is online.")
    driver.close()
except Exception as e:
    print(f"Failed to connect: {e}")
