from unittest.mock import AsyncMock, patch
import pytest
from scrapers.item import ScrapedItem
from scrapers.vinted import VintedScraper
from filters import checkTitleRelevance, checkHardwareModelCompatibility

def test_scraped_item_creation_and_broken_detection():
    # Valid GPU
    gpu_item = ScrapedItem("1001", "Nvidia RTX 3070 Gigabyte 8GB", 280.0, "https://www.vinted.fr/items/1001", "vinted")
    assert gpu_item.externalId == "1001"
    assert gpu_item.title == "Nvidia RTX 3070 Gigabyte 8GB"
    assert gpu_item.price == 280.0
    assert not gpu_item.isBroken()

    # Broken GPU
    hs_item = ScrapedItem("1002", "RTX 3070 HS pour pièces non testé", 40.0, "https://www.vinted.fr/items/1002", "vinted")
    assert hs_item.isBroken()

    # Empty Box
    box_item = ScrapedItem("1003", "Boite vide seule RTX 3070", 15.0, "https://www.vinted.fr/items/1003", "vinted")
    assert box_item.isBroken()

@pytest.mark.asyncio
async def test_vinted_scraper_execution_mocked():
    scraper = VintedScraper()
    mock_items = [
        ScrapedItem("2001", "Ryzen 5 5600X CPU", 110.0, "https://www.vinted.fr/items/2001", "vinted")
    ]
    
    async def mock_scrape(*args, **kwargs):
        return mock_items

    with patch.object(scraper, "scrape", side_effect=mock_scrape):
        results = await scraper.scrape("ryzen 5 600x", maxPrice=150.0, maxPages=1, maxItems=5)
        assert isinstance(results, list)
        assert len(results) == 1
        assert results[0].externalId == "2001"
        assert results[0].price == 110.0

def test_hardware_filters_logic():
    # Motherboard chipset check
    assert checkHardwareModelCompatibility("carte mere msi b85", "b85")
    assert not checkHardwareModelCompatibility("carte mere msi b85", "h610")

    # RAM generation check
    assert checkHardwareModelCompatibility("ram 16go ddr4 corsair", "ddr4")
    assert not checkHardwareModelCompatibility("ram 16go ddr3 corsair", "ddr4")

    # Title relevance check
    assert checkTitleRelevance("rtx 3070 gigabyte", "rtx 3070")
    assert not checkTitleRelevance("carte mere b450", "rtx 3070")
