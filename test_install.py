print('Testing imports...')
import_status = {}

try:
    import torch
    import_status['PyTorch'] = '✓'
except: 
    import_status['PyTorch'] = '✗'

try:
    import cv2
    import_status['OpenCV'] = '✓'
except:
    import_status['OpenCV'] = '✗'

try:
    import google.generativeai
    import_status['Gemini'] = '✓'
except:
    import_status['Gemini'] = '✗'

try:
    from ultralytics import YOLO
    import_status['YOLO'] = '✓'
except:
    import_status['YOLO'] = '✗'

try:
    import transformers
    import_status['Transformers'] = '✓'
except:
    import_status['Transformers'] = '✗'

for module, status in import_status.items():
    print(f'{status} {module}')

print('\nSetup complete! Next steps:')
print('1. Get Gemini API key from https://makersuite.google.com/app/apikey')
print('2. Update .env file with your API key')
print('3. Copy the Python code into each module file')
print('4. Run: python main.py')
