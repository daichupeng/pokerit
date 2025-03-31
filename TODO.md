# Pokerit TODO List

## Computer Vision Components

### Card Recognition
- [ ] Train/integrate card detection model (YOLOv8 recommended)
- [ ] Develop suit and rank classification system
- [ ] Implement template matching for cards
- [ ] Create calibration system for different poker clients
- [ ] Add confidence scoring for card recognition

### Action Detection
- [ ] Implement OCR for reading bet amounts
- [ ] Add UI element recognition for action buttons
- [ ] Create detection for player turns
- [ ] Add position recognition
- [ ] Implement stack size OCR

## Game State Tracking

- [ ] Add poker client-specific calibration
- [ ] Implement proper action validation
- [ ] Create state machine for game flow
- [ ] Add player tracking between hands
- [ ] Implement blind level detection
- [ ] Add support for different poker variants

## AI Strategy Engine

- [ ] Fine-tune prompts with expert poker knowledge
- [ ] Create comprehensive prompt templates for different situations
- [ ] Add hand strength evaluation
- [ ] Implement advanced hand analysis
- [ ] Add player profiling
- [ ] Create specialized prompts for tournament vs. cash games

## Screen Capture

- [ ] Add automatic poker client detection
- [ ] Implement dynamic region adjustment
- [ ] Add multi-monitor support
- [ ] Optimize capture performance
- [ ] Add support for window resizing

## GUI Improvements

- [ ] Add configuration panels for settings
- [ ] Implement hand history viewer
- [ ] Add player statistics dashboard
- [ ] Create visualization for suggested actions
- [ ] Add theme support
- [ ] Implement session tracking

## Database Enhancements

- [ ] Add data migration system
- [ ] Implement query optimization
- [ ] Add export/import functionality
- [ ] Create backup system
- [ ] Add advanced statistics and reporting

## Training Needed

### Card Recognition Model
1. Collect ~1000+ screenshots from target poker clients
2. Label card positions and values (using tools like LabelImg)
3. Train object detection model 
4. Fine-tune for specific poker clients

### Card Classification
1. Crop individual card images from screenshots
2. Label suit and rank for ~5000+ card images
3. Train CNN classifier
4. Integrate with detection model

### Action Detection
1. Collect ~500+ screenshots of different actions
2. Label action button positions and text
3. Train OCR model or use pre-trained models
4. Create template library for UI elements 