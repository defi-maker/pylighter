import json 
import httpx
import orjson
import logging

class HTTPException(Exception):
    """
    An exception class for HTTP errors, capturing the status code, error message, and response headers.

    Args:
        status_code (int): The HTTP status code of the error.
        message (str): The error message.
        headers (dict): The response headers associated with the error.
    """
    def __init__(self, status_code, message, headers, cargs=None):
        self.status_code = status_code
        self.message = message
        self.headers = headers
        self.cargs = {} if cargs is None else cargs

    def __repr__(self):
        return f'status{self.status_code} :: {self.message}\n{self.headers}' + (f'\n{json.dumps(self.cargs)}' if self.cargs else '')

    __str__ = __repr__


class HTTPClient:
    """
    An asynchronous HTTP aiosonic client for fast network requests and (de)serialization 
    of data packets. Automatic retries and error handling.

    Args:
        base_url (str, optional): The base URL for all requests. Defaults to an empty string.
        json_decoder (callable, optional): The JSON decoder function to use. Defaults to `orjson.loads`.
    """

    def __init__(self, base_url='', json_decoder=orjson.loads):
        self.client = None
        self.base_url = base_url
        self.json_decoder = json_decoder

    async def request(
        self,
        url='',
        endpoint='',
        method='GET',
        headers={"content-type": "application/json"},
        params = None,
        json = None,
        return_exceptions = False,
        retries = 2
    ):
        """
        Make an HTTP request and handle retries on failure.

        Args:
            url (str, optional): The full URL for the request. If not provided, `base_url` + `endpoint` is used. Defaults to an empty string.
            endpoint (str, optional): The endpoint to append to the base URL. Defaults to an empty string.
            method (str, optional): The HTTP method to use. Defaults to 'GET'.
            headers (dict, optional): The headers to include in the request. Defaults to {"content-type": "application/json"}.
            params (dict, optional): The URL parameters to include in the request. Defaults to None.
            json (dict): The json key-values to include in the request body. Defaults to None.
            return_exceptions (bool, optional): Whether to return exceptions instead of raising them. Defaults to False. No retries if True.
            retries (int, optional): The number of retries if the request fails. Defaults to 2.

        Returns:
            dict: The parsed JSON response if the request is successful.

        Raises:
            HTTPException: If the response status code is 400 or higher.
        """
        if not self.client:
            self.client = httpx.AsyncClient()
        try:
            url = url if url else self.base_url + endpoint
            url = url + f"?{params}" if isinstance(params, str) else url
            params = {} if isinstance(params, str) else params
            request_args = {
                "url": url,
                "method": method,
                "headers": headers,
                "params": params,
                "json": json
            }

            response = await self.client.request(**request_args)
            return await self.handler(response,cargs=request_args)
        except Exception as e:
            if return_exceptions:
                return e
            if retries > 0:
                await self.cleanup()
                self.client = httpx.AsyncClient()
                return await self.request(
                    url=url, 
                    endpoint=endpoint, 
                    method=method, 
                    headers=headers, 
                    params=params, 
                    json=json, 
                    retries=retries - 1
                )
            raise e

    async def handler(self, response, cargs={}):
        status_code = response.status_code
        if status_code < 400:
            return response.json() if response.text else {}
        try:
            err = response.text
            err = json.loads(err)
        except json.JSONDecodeError:
            pass
        finally:
            raise HTTPException(status_code=status_code, message=err, headers=response.headers, cargs=cargs)
            
    async def cleanup(self):
        try:
            if self.client:
                await self.client.aclose()
                await self.client.__aexit__(None, None, None)
                del self.client
        except:
            pass