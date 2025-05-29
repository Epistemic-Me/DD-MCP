# DD-MCP (Don't Die Model Context Protocol)

A FastAPI proxy service for integrating with the Don't Die API platform, providing Model Context Protocol (MCP) interfaces for AI agent interactions.

## Overview

DD-MCP is a microservice that acts as a bridge between AI agents and the Don't Die health platform. It provides a standardized MCP interface for accessing health metrics, biomarkers, protocols, and other wellness data.

## Features

- **MCP Protocol Support**: Standardized Model Context Protocol interfaces
- **Don't Die API Integration**: Secure proxy to Don't Die platform services
- **Redis Caching**: High-performance caching for frequently accessed data
- **Health Metrics**: Access to user health measurements and biomarkers
- **Protocol Management**: Integration with wellness protocols and routines

## Technology Stack

- **Framework**: FastAPI
- **Cache**: Redis
- **Authentication**: Don't Die API tokens
- **Protocol**: Model Context Protocol (MCP)

## Getting Started

### Prerequisites

- Python 3.8+
- Redis server
- Don't Die API credentials

### Installation

1. Clone the repository:
```bash
git clone https://github.com/Epistemic-Me/DD-MCP.git
cd DD-MCP
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up environment variables:
```bash
cp .env.example .env
# Edit .env with your configuration
```

4. Run the service:
```bash
uvicorn main:app --host 0.0.0.0 --port 8090
```

### Docker

```bash
docker build -t dd-mcp .
docker run -p 8090:8090 --env-file .env dd-mcp
```

## Configuration

Required environment variables:

- `DD_TOKEN`: Don't Die API token
- `DD_CLIENT_ID`: Don't Die client ID
- `REDIS_URL`: Redis connection URL (default: redis://localhost:6379/0)

## API Endpoints

- `GET /health`: Health check endpoint
- `POST /mcp/*`: MCP protocol endpoints
- See API documentation at `/docs` when running

## Development

### Running Tests

```bash
pytest
```

### Code Formatting

```bash
ruff format .
ruff check .
```

## License

MIT License - see LICENSE file for details.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## Support

For issues and questions, please use the GitHub issue tracker. 