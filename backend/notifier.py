import httpx
import logging

logger = logging.getLogger("LBCBot")

def sendDiscordNotification(webhookUrl: str, payload: dict) -> str:
    """
    Envoie un message riche (embed) ou texte sur Discord via Webhook.
    Ajoute wait=true pour récupérer et retourner l'ID du message envoyé.
    """
    if not webhookUrl:
        logger.warning("Aucun webhook Discord configuré, notification ignorée.")
        return None

    # Ajouter wait=true pour récupérer les infos du message créé (dont son ID)
    separator = "&" if "?" in webhookUrl else "?"
    url = f"{webhookUrl}{separator}wait=true"

    try:
        response = httpx.post(url, json=payload, timeout=10)
        if response.status_code in [200, 204]:
            logger.info("Notification Discord envoyée avec succès.")
            try:
                data = response.json()
                return data.get("id")
            except Exception:
                logger.warning("Impossible de décoder la réponse JSON de Discord pour extraire le message ID.")
                return None
        else:
            logger.error("Échec de la notification Discord. Code statut : %s, Réponse : %s", response.status_code, response.text)
    except Exception as e:
        logger.error("Une erreur est survenue lors de l'envoi de la notification Discord : %s", e)
    return None

def deleteDiscordMessage(webhookUrl: str, messageId: str) -> bool:
    """
    Supprime un message précédemment envoyé par ce webhook sur Discord.
    """
    if not webhookUrl or not messageId:
        return False

    # Extraire l'URL de base du webhook (sans les paramètres éventuels de token/wait)
    base_url = webhookUrl.split("?")[0]
    delete_url = f"{base_url}/messages/{messageId}"

    try:
        response = httpx.delete(delete_url, timeout=10)
        # Gestion automatique du Rate Limit Discord (429)
        if response.status_code == 429:
            try:
                retry_after = float(response.json().get("retry_after", 1.0))
            except Exception:
                retry_after = 4.0
            logger.warning("Rate limited par Discord. Attente de %s secondes...", retry_after)
            import time
            time.sleep(retry_after)
            response = httpx.delete(delete_url, timeout=10)  # Retente la suppression
            
        if response.status_code == 204:
            logger.info("Message Discord %s supprimé du canal.", messageId)
            return True
        else:
            logger.error("Échec de la suppression du message Discord %s. Code statut : %s, Réponse : %s", messageId, response.status_code, response.text)
    except Exception as e:
        logger.error("Erreur lors de la suppression du message Discord : %s", e)
    return False
