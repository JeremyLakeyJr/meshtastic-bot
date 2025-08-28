# Meshtastic AI DM Bot - Project Documentation

## Overview

The Meshtastic AI DM Bot is a nodeless chatbot that integrates with Meshtastic mesh networks via MQTT. It provides AI-powered responses using Google Gemini and manages private user sessions through direct messages.

## Architecture

### Core Components

1. **Main Bot (`main.py`)**
   - Orchestrates all components
   - Handles MQTT connection and message routing
   - Manages command processing and response flow

2. **Protobuf Parser (`protobuf_parser.py`)**
   - Parses Meshtastic ServiceEnvelope protobuf messages
   - Extracts text content and metadata
   - Identifies message types and routing information

3. **Session Manager (`session_manager.py`)**
   - Manages user sessions and authentication
   - Handles session timeouts and cleanup
   - Tracks active user states

4. **AI Handler (`ai_handler.py`)**
   - Interfaces with Google Gemini API
   - Manages AI response generation
   - Handles retry logic and error recovery

5. **Response Chunker (`response_chunker.py`)**
   - Splits AI responses into appropriate chunk sizes
   - Ensures mesh-friendly message lengths
   - Optimizes chunking for readability

### Data Flow

```
MQTT Message → Protobuf Parser → Command Handler → AI Handler → Response Chunker → Downlink Publisher
```

## Setup Instructions

### Prerequisites

- Python 3.11+
- MQTT broker access
- Google Gemini API key
- Meshtastic mesh network

### Installation

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd meshtastic-ai-dm-bot
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure the bot:**
   ```bash
   cp config.env.example config.env
   # Edit config.env with your settings
   ```

4. **Test the installation:**
   ```bash
   python test_bot.py
   ```

### Configuration

Key configuration options in `config.env`:

- **MQTT Settings**: Host, port, credentials
- **Mesh Settings**: Region, version, topic filters
- **AI Settings**: Gemini API key, model configuration
- **Response Settings**: Chunk size, delay timing

## Usage

### Starting the Bot

```bash
# Using the startup script (recommended)
python start.py

# Or directly
python main.py
```

### Bot Commands

#### Public Channel
- `/bot` - Start a private session with the bot

#### Private DM
- `/ai <question>` - Ask Gemini a question
- `/ai` (no text) - Get help

### Message Flow

1. **Public Command**: User sends `/bot` in public channel
2. **Session Creation**: Bot creates/refreshes user session
3. **Private Response**: Bot sends DM confirming session start
4. **AI Interaction**: User sends `/ai` commands in private DM
5. **Chunked Response**: Bot sends AI responses in chunks with delays

## Technical Details

### Protobuf Handling

The bot subscribes to `msh/#` and attempts to parse each MQTT message as a Meshtastic ServiceEnvelope. Messages that fail to parse are ignored.

### Text Message Detection

Text messages are identified by `packet.decoded.portnum == TEXT_MESSAGE_APP` (port 1).

### Public vs Private Messages

- **Public**: `packet.to == 0xFFFFFFFF`
- **Private**: Any other `packet.to` value

### Response Chunking

- Maximum chunk size: 180 bytes (configurable)
- Delay between chunks: 1.2 seconds (configurable)
- Smart chunking preserves sentence boundaries

### Session Management

- Sessions expire after 1 hour of inactivity
- Automatic cleanup every 5 minutes
- Session refresh on new `/bot` commands

## Error Handling

### MQTT Connection Issues
- Automatic reconnection attempts
- Graceful degradation on connection loss
- Logging of connection state changes

### AI API Failures
- Retry logic with exponential backoff
- Fallback responses on complete failure
- Detailed error logging

### Protobuf Parsing Errors
- Silent failure for malformed messages
- Debug logging for troubleshooting
- Graceful continuation of operation

## Monitoring and Logging

### Log Levels
- **INFO**: Normal operation events
- **WARNING**: Non-critical issues
- **ERROR**: Critical failures
- **DEBUG**: Detailed debugging information

### Key Metrics
- Active session count
- Message processing rates
- AI response times
- Error frequencies

## Security Considerations

### API Key Protection
- Store API keys in environment variables
- Never commit secrets to version control
- Use `.gitignore` to exclude config files

### MQTT Security
- Use authentication credentials
- Consider TLS encryption for production
- Validate message sources

### Session Security
- Session timeouts prevent abuse
- User isolation through session management
- No persistent user data storage

## Troubleshooting

### Common Issues

1. **MQTT Connection Failed**
   - Check broker address and credentials
   - Verify network connectivity
   - Check firewall settings

2. **AI Responses Not Working**
   - Verify Gemini API key
   - Check API quota and limits
   - Test API connectivity

3. **Messages Not Received**
   - Verify topic subscription
   - Check protobuf parsing
   - Review message format

### Debug Mode

Enable debug logging by modifying the logging level in `main.py`:

```python
logging.basicConfig(level=logging.DEBUG)
```

## Development

### Adding New Commands

1. Add command handler method to `MeshtasticAIBot`
2. Update message processing logic
3. Add tests in `test_bot.py`

### Extending AI Capabilities

1. Modify `AIHandler` class
2. Add new model support
3. Implement custom prompt engineering

### Customizing Response Format

1. Modify `ResponseChunker` class
2. Adjust chunking algorithms
3. Add new response types

## Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Submit a pull request

## License

[Add your license information here]

## Support

For issues and questions:
- Check the troubleshooting section
- Review the logs for error details
- Open an issue on the repository
