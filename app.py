
from flask import Flask, request, render_template, session, redirect, url_for, jsonify
from flask_session import Session
import requests
from xml.etree import ElementTree
from datetime import datetime, timedelta
import pytz
from dateutil import parser, tz
import os
from redis import Redis
from flask_cors import CORS

app = Flask(__name__)
CORS(app)
app.secret_key = os.urandom(24)  # Secure random key
app.config['SESSION_TYPE'] = 'redis'
app.config['SESSION_REDIS'] = Redis(host='redis-16031.c135.eu-central-1-1.ec2.redns.redis-cloud.com', port=16031, db=0, password='W7BhXAuUWFNmenf026i1wj5mFK4xS7V0')
app.config['SESSION_PERMANENT'] = True
app.config['SESSION_USE_SIGNER'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=1)

Session(app)
# Add this in your app.py after setting up Redis
try:
    test_key = 'redis_test'
    app.config['SESSION_REDIS'].set(test_key, '1')
    assert app.config['SESSION_REDIS'].get(test_key) == b'1', "Redis connection failed"
    print("Redis is connected and working.")
except Exception as e:
    print("Failed to connect or verify Redis:", e)


def utc_to_local(utc_dt, local_zone):
    utc_dt = datetime.strptime(utc_dt, '%Y-%m-%dT%H:%M:%SZ')
    utc_zone = pytz.timezone('UTC')
    local_zone = pytz.timezone(local_zone)
    local_dt = utc_zone.localize(utc_dt).astimezone(local_zone)
    return local_dt  # Return the datetime object, not a string

def get_hours_to_left(schedule_time, local_zone='Europe/Oslo'):
    now = datetime.now(tz.gettz(local_zone))
    schedule = parser.parse(schedule_time)
    schedule = schedule.astimezone(tz.gettz(local_zone))
    if schedule > now:
        delta = schedule - now
        hours, remainder = divmod(delta.seconds, 3600)
        minutes = remainder // 60
        return f"{hours:02}:{minutes:02}"
    else:
        return "00:00"
def get_flight_data(airport_code, direction, flight_type='A'):
    url = f"http://flydata.avinor.no/XmlFeed.asp?TimeFrom=1&TimeTo=7&airport={airport_code}&direction={direction}&lastUpdate=2009-03-10T15:03:00Z"
    response = requests.get(url)
    active_flights = []
    archived_flights = []
    if response.status_code == 200:
        root = ElementTree.fromstring(response.content)
        for flight in root.findall('.//flight'):
            airline = flight.find('flight_id').text[:2]  # Extract the airline code
            dom_int = flight.find('dom_int').text if flight.find('dom_int') is not None else 'A'
            if flight_type != 'A' and dom_int != flight_type:
                continue  # Skip flights not matching the selected type
            schedule_time = flight.find('schedule_time').text
            local_schedule_time = utc_to_local(schedule_time, 'Europe/Oslo')
            hours_to_left = get_hours_to_left(schedule_time)
            flight_data = {
                'flight_id': flight.find('flight_id').text,
                'dom_int': dom_int,  # Include domestic/international indicator
                'schedule_time': local_schedule_time.strftime('%d-%m-%Y %H:%M'),
                'hours_to_left': hours_to_left,
                'arr_dep': flight.find('arr_dep').text,
                'airport': flight.find('airport').text,
                'gate': flight.find('gate').text if flight.find('gate') is not None else 'N/A',
                'status': flight.find('status').get('code') if flight.find('status') is not None else 'Scheduled',
                'status_time': flight.find('status').get('time') if flight.find('status') is not None else 'No update'
            }
            if hours_to_left == '00:00':
                archived_flights.append(flight_data)
            else:
                active_flights.append(flight_data)
    return {'active': active_flights, 'archived': archived_flights}

@app.route('/')
def home():
    airport_code = request.args.get('airport', 'OSL')
    direction = request.args.get('direction', 'D')
    flight_type = request.args.get('flight_type', 'A')  # Retrieve the flight type from request arguments
    flights = get_flight_data(airport_code, direction, flight_type)
    return render_template('flights.html', flights=flights)

# Baggage Handling COUNT and DEVLERIED 
@app.route('/baggage_arrived', methods=['POST'])
def baggage_arrived():
    flight_id = request.form.get('flightId')
    print("Received flight ID:", flight_id)  # Debug log
    if flight_id:
        session[flight_id] = session.get(flight_id, 0) + 1
        session.modified = True
        print("Updated baggage count for flight:", flight_id, session[flight_id])  # More debug info
        return jsonify({"status": "success", "message": "Baggage count updated", "count": session[flight_id]})
    return jsonify({"status": "error", "message": "No Flight ID provided"}), 400

@app.route('/baggage_delivered', methods=['POST'])
def baggage_delivered():
    flight_id = request.form.get('flightId')
    if flight_id:
        delivered_key = 'delivered_' + flight_id
        session[delivered_key] = session.get(delivered_key, 0) + session.get(flight_id, 0)
        session[flight_id] = 0  # Reset the count for new bags
        session.modified = True
        return jsonify({
            "status": "success",
            "message": "Delivery count updated",
            "delivered_count": session[delivered_key],
            "new_count": session[flight_id]
        }), 200
    return jsonify({"status": "error", "message": "No Flight ID provided"}), 400


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
