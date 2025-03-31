# Pokerit TODO List

## Backend Components

### Computer Vision API
- [ ] Create image processing API endpoint
- [ ] Implement image reception from browser extension
- [ ] Add card detection model integration
- [ ] Develop OCR for poker client text
- [ ] Add confidence scoring for recognition

### Game State API
- [ ] Create WebSocket-based real-time update system
- [ ] Implement proper game state validation
- [ ] Add support for different poker variants
- [ ] Create state machine for game flow
- [ ] Implement session management

### AI Strategy Engine
- [ ] Fine-tune Claude prompts for poker strategy
- [ ] Create specialized prompts for different game situations
- [ ] Add hand strength evaluation
- [ ] Implement player profiling
- [ ] Create tournament vs. cash game specialized advice

### Database and Storage
- [ ] Implement proper session persistence
- [ ] Create user authentication system
- [ ] Add data export/import functionality
- [ ] Implement query optimization
- [ ] Add backup system

## Frontend Components

### React Application
- [ ] Implement WebSocket client connection
- [ ] Create responsive game state display
- [ ] Add visual card and chip representations
- [ ] Implement session management UI
- [ ] Add settings panel

### Data Visualization
- [ ] Create hand history viewer
- [ ] Implement player statistics dashboard
- [ ] Add interactive charts for performance metrics
- [ ] Create visualization for suggested actions
- [ ] Add theme support

## Browser Extension

### Screen Capture
- [ ] Optimize image compression
- [ ] Add region selection capability
- [ ] Implement auto-detection of poker clients
- [ ] Add privacy controls
- [ ] Create debug mode

### Communication
- [ ] Implement secure WebSocket communication
- [ ] Add reconnection logic
- [ ] Create offline buffering
- [ ] Implement status monitoring
- [ ] Add error handling and recovery

## DevOps

### Deployment
- [ ] Configure production-ready Docker settings
- [ ] Set up CI/CD pipeline
- [ ] Implement proper logging
- [ ] Add monitoring and alerting
- [ ] Create backup strategy

### Security
- [ ] Implement proper authentication
- [ ] Add API key management
- [ ] Create rate limiting
- [ ] Add input validation and sanitization
- [ ] Implement secure WebSocket connections

## Training Needed

### Card Recognition Model
1. Collect screenshots from target poker clients
2. Label card positions and values
3. Train object detection model
4. Fine-tune for specific poker clients

### Action Detection
1. Collect screenshots of different actions
2. Label action elements and text
3. Train OCR model or adapt pre-trained ones
4. Create template library for UI elements 