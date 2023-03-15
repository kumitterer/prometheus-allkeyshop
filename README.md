# Prometheus Exporter for allkeyshop.com

This is a simple exporter for allkeyshop.com. It exports the lowest price for a 
given game.

## Prerequisites

- Python >= 3.8
- prometheus-client (pip install prometheus-client)

## Configuration

The exporter is configured using settings.ini. The provided settings.dist.ini 
is a template for the configuration file.

To add a new game/product, add a new section to the configuration file. The 
section name can be either the product ID from allkeyshop.com or the product 
name.

## Usage

To run the exporter, simply execute the allkeyshop.py script. The exporter will
listen on port 8090 by default.

To get a list of all available command line options, run the following command:

```bash
./allkeyshop.py --help
```

A sample output of the exporter looks like this:

```
# HELP allkeyshop_best_price Best price for a product on allkeyshop.com
# TYPE allkeyshop_best_price gauge
allkeyshop_best_price{currency="eur",product_name="Persona 5 Royal"} 49.99
allkeyshop_best_price{currency="eur",product_name="Cyberpunk 2077"} 49.48
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file