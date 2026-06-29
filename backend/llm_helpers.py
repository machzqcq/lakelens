import logging
import os
import warnings

logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore", category=UserWarning, module="pyspark")

def get_spark_session(app_name="default",driver_mem="4g",exec_mem="8g",exec_cores="2",shuffle_partitions="5", sparkwarehouse_dir=None, enable_hive=False, enable_thrift_server=False, thrift_port=10000):
    from pyspark.sql import SparkSession
    from pyspark.conf import SparkConf
    import os
    import setuptools  # distutils is deprecated and absorbed into setuptools since 3.12 and required for .toPandas() to work properly
    
    config = SparkConf()
    # Configure crealytics spark excel driver via Maven packages
    logger.info("📦 Configuring crealytics spark excel driver via Maven packages...")
    config.set("spark.jars.packages", "com.crealytics:spark-excel_2.12:3.5.1_0.20.4")
    config.set("spark.driver.memory", driver_mem)
    config.set("spark.executor.memory", exec_mem)
    config.set("spark.executor.cores", exec_cores)
    config.set("spark.sql.ansi.enabled", "true") ## Enable ANSI SQL compliance
    config.set("spark.sql.inMemoryColumnarStorage.compressed","true")
    config.set("dfs.client.read.shortcircuit.skip.checksum", "true")
    config.set("spark.sql.execution.arrow.pyspark.enabled", "true") ## for .toPandas() to work properly
    config.set("spark.sql.autoBroadcastJoinThreshold", -1) ## remove the limit of 10mb over network limit for broadcast joins
    
    # Add Thrift server configuration if it will be enabled
    if enable_thrift_server:
        config.set("spark.sql.hive.thriftServer.singleSession", "true")
        config.set("hive.server2.thrift.port", str(thrift_port))
    
    # Set the number of shuffle partitions based on the parameter
    config.set("spark.sql.shuffle.partitions", shuffle_partitions)

    # Cluster mode
    # https://spark.apache.org/docs/latest/submitting-applications.html
    # config.setMaster("spark://192.168.0.111:7077") # DONT SET THIS If spark is started in local cluster mode
    if sparkwarehouse_dir is None:
        sparkwarehouse_dir = os.getcwd() + "/spark-warehouse"
        builder = SparkSession.builder.master("local[*]").appName(app_name).config("spark.sql.warehouse.dir", sparkwarehouse_dir).config(conf=config)
        spark = builder.enableHiveSupport().getOrCreate() if enable_hive else builder.getOrCreate()
    else:
        fullpath = os.path.abspath(os.path.join(os.getcwd(), sparkwarehouse_dir))
        metastore_dir = os.path.join(os.path.dirname(fullpath), "metastore_db")
        print(f"Spark warehouse directory: {fullpath}")
        print(f"Metastore directory: {metastore_dir}")
        builder = SparkSession.builder.master("local[*]").appName(app_name).config("spark.sql.warehouse.dir", fullpath).config(conf=config)
        if enable_hive:
            builder = builder.config("javax.jdo.option.ConnectionURL", f"jdbc:derby:{metastore_dir};create=true").enableHiveSupport()
        spark = builder.getOrCreate()
    
    # Start Apache Thrift server if enabled and Hive support is enabled
    if enable_thrift_server and enable_hive:
        try:
            _start_thrift_server_py4j(spark, thrift_port)
        except Exception as e:
            print(f"\n[WARN] Thrift server setup note: {e}")
    
    return spark

import os
from pyspark.sql import SparkSession
from pyspark.conf import SparkConf

def get_spark_session_multiple_catalogs(
    app_name="multi_catalog_app",
    driver_mem="4g",
    exec_mem="2g",
    exec_cores="2",
    shuffle_partitions="5",
    sparkwarehouse_dir=None,
    catalogs=None, 
    enable_hive=False
):
    sparkwarehouse_dir = os.path.abspath(sparkwarehouse_dir or "./spark-warehouse")
    os.makedirs(sparkwarehouse_dir, exist_ok=True)

    config = SparkConf()
    
    # 1. Essential Packages
    # Ensure these versions match your Spark installation
    config.set("spark.jars.packages", "com.crealytics:spark-excel_2.12:3.5.1_0.20.4,io.delta:delta-spark_2.12:3.2.0")
    
    # 2. Delta Extension (CRITICAL)
    # This extension automatically "upgrades" the default spark_catalog to support Delta.
    config.set("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
    
    # 3. FIX: DELETE THE MANUAL spark_catalog CONFIG
    # -------------------------------------------------------------------------
    # DO NOT set this. It conflicts with the extension and causes the NPE.
    # config.set("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog") 
    # -------------------------------------------------------------------------

    # 4. Configure CUSTOM Catalogs
    # Custom catalogs (non-default) DO need the explicit class definition.
    if catalogs:
        for cat_name, path in catalogs.items():
            abs_path = os.path.abspath(path)
            os.makedirs(abs_path, exist_ok=True)
            
            # Implementation class
            config.set(f"spark.sql.catalog.{cat_name}", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
            # Warehouse location
            config.set(f"spark.sql.catalog.{cat_name}.warehouse", abs_path)

    # 5. Standard Resources
    config.set("spark.driver.memory", driver_mem)
    config.set("spark.executor.memory", exec_mem)
    config.set("spark.sql.shuffle.partitions", shuffle_partitions)
    config.set("spark.sql.warehouse.dir", sparkwarehouse_dir)

    builder = SparkSession.builder \
        .master("local[*]") \
        .appName(app_name) \
        .config(conf=config)
    
    if enable_hive:
        metastore_dir = os.path.join(os.path.dirname(sparkwarehouse_dir), "metastore_db")
        builder.config("javax.jdo.option.ConnectionURL", f"jdbc:derby:{metastore_dir};create=true")
        builder.enableHiveSupport()

    return builder.getOrCreate()

def _start_thrift_server_py4j(spark, port=10000):
    """
    Start the Apache Thrift server (HiveServer2) for remote SQL access using Py4J.
    
    This method uses the Java gateway to directly invoke HiveThriftServer2 startup.
    In Spark 3.x, uses the _jsparkSession object.
    
    Args:
        spark: Active SparkSession with Hive support enabled
        port (int): Port for Thrift server (default: 10000)
    
    Raises:
        Exception: If server fails to start
    """
    import time
    import socket
    
    try:
        # Check if port is already in use
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(('127.0.0.1', port))
        sock.close()
        
        if result == 0:
            print(f"[INFO] Port {port} is already in use. Thrift server may already be running.")
            return
        
        # Get the Spark context and Java gateway
        sc = spark.sparkContext
        jvm = sc._gateway.jvm
        
        print(f"Starting Thrift server on port {port}...")
        
        # In Spark 3.5.4, HiveThriftServer2 can be started directly
        # The startWithContext method requires SQLContext/HiveContext, not SparkSession
        # So we use the session's internal SQLContext wrapper
        hive_server = jvm.org.apache.spark.sql.hive.thriftserver.HiveThriftServer2
        sql_context = jvm.org.apache.spark.sql.SQLContext(spark._jsparkSession)
        hive_server.startWithContext(sql_context)
        
        # Give the server a moment to initialize
        time.sleep(2)
        
        print(f"[OK] Thrift server started successfully on port {port}")
        print(f"  Connection string: jdbc:hive2://localhost:{port}")
        
    except Exception as e:
        raise Exception(f"Failed to start Thrift server: {str(e)}")



def stop_thrift_server(port=10000):
    """
    Stop the Apache Thrift server (HiveServer2).
    
    Note: When using Py4J in-process startup, the Thrift server runs within the 
    same JVM as Spark. To stop it, stop the Spark session instead using stop_spark_session().
    
    This function is kept for compatibility and port monitoring purposes.
    
    Args:
        port (int): Port of the Thrift server (default: 10000)
    """
    import subprocess
    import os
    import platform
    
    try:
        if platform.system() == "Windows":
            # Windows: Use taskkill to find process by port
            cmd = f'netstat -ano | findstr :{port}'
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            if result.stdout:
                pid = result.stdout.strip().split()[-1]
                subprocess.run(f'taskkill /PID {pid} /F', shell=True)
                print(f"✓ Thrift server stopped (PID: {pid})")
            else:
                print(f"⚠ No process found on port {port}")
        else:
            # Unix/Linux: Use lsof and kill
            cmd = f'lsof -i :{port} | grep LISTEN | awk "{{print $2}}" | xargs kill -9'
            subprocess.run(cmd, shell=True)
            print(f"✓ Thrift server stopped on port {port}")
    except Exception as e:
        print(f"Note: Could not stop external Thrift server: {e}. If using Py4J in-process mode, call stop_spark_session() instead.")


def stop_spark_session(spark):
    try:
        spark.stop()
        print("Spark session stopped")
    except:
        print("Error stopping spark session")

def generate_sql_from_text(
    user_query: str,
    system_prompt: str = None,
    model: str = "gemini-2.0-flash",
    provider: str = "google",
    api_key: str = None,
    temperature: float = 0.7,
    max_tokens: int = 2048
) -> str:
    """
    Generate SQL queries from natural language using various LLM providers.
    
    Args:
        user_query (str): The natural language question/request for SQL generation
        system_prompt (str): The system prompt to guide SQL generation. If None, loads from gemini_text_to_sql_prompt.txt
        model (str): The model ID to use (default: "gemini-2.0-flash")
        provider (str): LLM provider - "google", "anthropic", "openai", or "deepseek" (default: "google")
        api_key (str): API key for the provider. If None, uses provider-specific env var
        temperature (float): Temperature for model generation (0-2, default: 0.7)
        max_tokens (int): Maximum tokens in the response (default: 2048)
    
    Returns:
        str: Generated SQL query
    
    Raises:
        ValueError: If API key is not provided and env var is not set, or invalid provider
        Exception: If API call fails
    """
    import os
    
    provider = provider.lower()
    
    # Provider-specific environment variable names
    env_var_map = {
        "google": "GOOGLE_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "deepseek": "OPENROUTER_API_KEY",
        "ollama": "OLLAMA_HOST",
        "vllm": "VLLM_BASE_URL",
        "azure": "AZURE_OPENAI_API_KEY",
    }

    if provider not in env_var_map:
        raise ValueError(f"Invalid provider '{provider}'. Must be one of: {list(env_var_map.keys())}")

    # Get API key (Ollama / vLLM don't need one by default, just a host URL)
    if api_key is None:
        if provider == "ollama":
            api_key = "ollama"  # dummy key; Ollama doesn't require auth
        elif provider == "vllm":
            api_key = os.getenv("VLLM_API_KEY", "EMPTY")  # vLLM defaults to "EMPTY" unless --api-key set
        else:
            api_key = os.getenv(env_var_map[provider])
            if not api_key:
                raise ValueError(
                    f"API key not provided. Pass api_key parameter or set {env_var_map[provider]} environment variable."
                )

    # Load system prompt from file if not provided
    if system_prompt is None:
        prompt_file = os.path.join(os.path.dirname(__file__), "../prompts", "gemini_text_to_sql_prompt.txt")
        try:
            with open(prompt_file, "r") as f:
                system_prompt = f.read()
        except FileNotFoundError:
            raise FileNotFoundError(
                f"System prompt file not found at {prompt_file}. "
                "Please provide system_prompt parameter or ensure gemini_text_to_sql_prompt.txt exists."
            )

    try:
        if provider == "anthropic":
            from anthropic import Anthropic

            client = Anthropic(api_key=api_key)
            generated_sql = ""

            try:
                with client.messages.stream(
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system=system_prompt,
                    messages=[
                        {"role": "user", "content": user_query}
                    ]
                ) as stream:
                    for text in stream.text_stream:
                        print(text, end="", flush=True)
                        generated_sql += text

                print()  # Add newline after streaming
            except Exception as stream_error:
                # Capture full error details for debugging
                error_details = str(stream_error)
                print(f"\n[DEBUG] Full Anthropic error: {error_details}", flush=True)
                raise

        elif provider == "google":
            from google import genai

            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=model,
                contents=user_query,
                config=genai.types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                ),
            )
            generated_sql = response.text

        elif provider == "azure":
            from openai import AzureOpenAI

            client = AzureOpenAI(
                api_key=api_key,
                api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
                azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT", ""),
            )
            deployment = model or os.getenv("AZURE_OPENAI_DEPLOYMENT", "")
            response = client.chat.completions.create(
                model=deployment,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_query},
                ],
                max_completion_tokens=max_tokens,
            )
            generated_sql = response.choices[0].message.content

        else:  # openai, deepseek, ollama, vllm (OpenAI-compatible providers)
            from openai import OpenAI

            ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
            vllm_base = os.getenv("VLLM_BASE_URL", "http://localhost:8000").rstrip("/")
            if not vllm_base.endswith("/v1"):
                vllm_base = f"{vllm_base}/v1"
            base_url_map = {
                "openai": None,
                "deepseek": "https://openrouter.ai/api/v1",
                "ollama": f"{ollama_host}/v1",
                "vllm": vllm_base,
            }

            client_args = {"api_key": api_key}
            if base_url_map.get(provider) is not None:
                client_args["base_url"] = base_url_map[provider]

            client = OpenAI(**client_args)

            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_query},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            generated_sql = response.choices[0].message.content

        return generated_sql

    except Exception as e:
        raise Exception(f"Error calling {provider} API: {str(e)}")


def generate_sql_from_text_with_config(
    user_query: str,
    system_prompt_file: str = None,
    **kwargs
) -> str:
    """
    Convenience wrapper for generate_sql_from_text that loads system prompt from file path.
    
    Args:
        user_query (str): The natural language question/request for SQL generation
        system_prompt_file (str): Path to system prompt file (default: gemini_text_to_sql_prompt.txt)
        **kwargs: Additional arguments to pass to generate_sql_from_text
            (model, provider, api_key, temperature, max_tokens)
    
    Returns:
        str: Generated SQL query
    """
    import os
    
    if system_prompt_file is None:
        system_prompt_file = os.path.join(
            os.path.dirname(__file__), 
            "..", 
            "gemini_text_to_sql_prompt.txt"
        )
    
    with open(system_prompt_file, "r") as f:
        system_prompt = f.read()
    
    return generate_sql_from_text(
        user_query=user_query,
        system_prompt=system_prompt,
        **kwargs
    )


def generate_pyspark_code_from_text(
    user_query: str,
    system_prompt: str = None,
    model: str = "gemini-2.0-flash",
    provider: str = "google",
    api_key: str = None,
    temperature: float = 0.7,
    max_tokens: int = 10000
) -> str:
    """
    Generate PySpark code from natural language using various LLM providers.
    
    Args:
        user_query (str): The natural language question/request for PySpark code generation
        system_prompt (str): The system prompt to guide code generation. If None, loads from gemini_text_to_pyspark_code_prompt.txt
        model (str): The model ID to use (default: "gemini-2.0-flash")
        provider (str): LLM provider - "google", "anthropic", "openai", or "deepseek" (default: "google")
        api_key (str): API key for the provider. If None, uses provider-specific env var
        temperature (float): Temperature for model generation (0-2, default: 0.7)
        max_tokens (int): Maximum tokens in the response (default: 10000)
    
    Returns:
        str: Generated PySpark code
    
    Raises:
        ValueError: If API key is not provided and env var is not set, or invalid provider
        Exception: If API call fails
    """
    import os
    
    provider = provider.lower()
    
    # Provider-specific environment variable names
    env_var_map = {
        "google": "GOOGLE_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "deepseek": "OPENROUTER_API_KEY",
        "ollama": "OLLAMA_HOST",
        "vllm": "VLLM_BASE_URL",
        "azure": "AZURE_OPENAI_API_KEY",
    }

    if provider not in env_var_map:
        raise ValueError(f"Invalid provider '{provider}'. Must be one of: {list(env_var_map.keys())}")

    # Get API key (Ollama / vLLM don't need one by default, just a host URL)
    if api_key is None:
        if provider == "ollama":
            api_key = "ollama"  # dummy key; Ollama doesn't require auth
        elif provider == "vllm":
            api_key = os.getenv("VLLM_API_KEY", "EMPTY")  # vLLM defaults to "EMPTY" unless --api-key set
        else:
            api_key = os.getenv(env_var_map[provider])
            if not api_key:
                raise ValueError(
                    f"API key not provided. Pass api_key parameter or set {env_var_map[provider]} environment variable."
                )

    # Load system prompt from file if not provided
    if system_prompt is None:
        prompt_file = os.path.join(os.path.dirname(__file__), "../prompts", "gemini_text_to_pyspark_code_prompt.txt")
        try:
            with open(prompt_file, "r") as f:
                system_prompt = f.read()
        except FileNotFoundError:
            raise FileNotFoundError(
                f"System prompt file not found at {prompt_file}. "
                "Please provide system_prompt parameter or ensure gemini_text_to_pyspark_code_prompt.txt exists."
            )

    try:
        if provider == "anthropic":
            from anthropic import Anthropic

            client = Anthropic(api_key=api_key)
            generated_code = ""

            try:
                with client.messages.stream(
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system=system_prompt,
                    messages=[
                        {"role": "user", "content": user_query}
                    ]
                ) as stream:
                    for text in stream.text_stream:
                        print(text, end="", flush=True)
                        generated_code += text

                print()  # Add newline after streaming
            except Exception as stream_error:
                # Capture full error details for debugging
                error_details = str(stream_error)
                print(f"\n[DEBUG] Full Anthropic error: {error_details}", flush=True)
                raise

        elif provider == "google":
            from google import genai

            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=model,
                contents=user_query,
                config=genai.types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                ),
            )
            generated_code = response.text

        elif provider == "azure":
            from openai import AzureOpenAI

            client = AzureOpenAI(
                api_key=api_key,
                api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
                azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT", ""),
            )
            deployment = model or os.getenv("AZURE_OPENAI_DEPLOYMENT", "")
            response = client.chat.completions.create(
                model=deployment,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_query},
                ],
                max_completion_tokens=max_tokens,
            )
            generated_code = response.choices[0].message.content

        else:  # openai, deepseek, ollama, vllm (OpenAI-compatible providers)
            from openai import OpenAI

            ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
            vllm_base = os.getenv("VLLM_BASE_URL", "http://localhost:8000").rstrip("/")
            if not vllm_base.endswith("/v1"):
                vllm_base = f"{vllm_base}/v1"
            base_url_map = {
                "openai": None,
                "deepseek": "https://openrouter.ai/api/v1",
                "ollama": f"{ollama_host}/v1",
                "vllm": vllm_base,
            }

            client_args = {"api_key": api_key}
            if base_url_map.get(provider) is not None:
                client_args["base_url"] = base_url_map[provider]

            client = OpenAI(**client_args)

            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_query},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            generated_code = response.choices[0].message.content

        return generated_code

    except Exception as e:
        raise Exception(f"Error calling {provider} API: {str(e)}")


def get_available_models():
    """
    Query model providers at runtime to get all available models.
    
    Returns:
        dict: Dictionary mapping provider names to list of available models
    """
    import os
    from openai import OpenAI
    
    MODEL_OPTIONS = {}
    
    # Provider configuration
    providers_config = {
        "google": {
            "api_key_env": "GOOGLE_API_KEY",
            "base_url": None,
            "type": "google"
        },
        "anthropic": {
            "api_key_env": "ANTHROPIC_API_KEY",
            "base_url": None,
            "type": "anthropic"
        },
        "openai": {
            "api_key_env": "OPENAI_API_KEY",
            "base_url": None,
            "type": "openai"
        },
        "deepseek": {
            "api_key_env": "OPENROUTER_API_KEY",
            "base_url": "https://openrouter.ai/api/v1",
            "type": "openrouter"
        },
        "ollama": {
            "api_key_env": "OLLAMA_HOST",
            "base_url": None,  # resolved dynamically from OLLAMA_HOST
            "type": "ollama"
        },
        "vllm": {
            "api_key_env": "VLLM_BASE_URL",
            "base_url": None,  # resolved dynamically from VLLM_BASE_URL
            "type": "vllm"
        },
        "azure": {
            "api_key_env": "AZURE_OPENAI_API_KEY",
            "base_url": None,  # resolved from AZURE_OPENAI_ENDPOINT
            "type": "azure"
        }
    }
    
    for provider, config in providers_config.items():
        # Ollama / vLLM don't need an API key — just check if host is reachable
        if config["type"] == "ollama":
            api_key = "ollama"  # dummy key for OpenAI client compat
        elif config["type"] == "vllm":
            api_key = os.getenv("VLLM_API_KEY", "EMPTY")  # vLLM default
        else:
            api_key = os.getenv(config["api_key_env"])
            if not api_key:
                print(f"⚠ Warning: {config['api_key_env']} not found, skipping {provider}")
                continue
            # Strip whitespace and quotes that might be in .env file
            api_key = api_key.strip().strip('"').strip("'")
        
        try:
            if config["type"] == "anthropic":
                # Query available Anthropic models using the SDK
                from anthropic import Anthropic
                
                client = Anthropic(api_key=api_key)
                
                # List all available models
                models_response = client.models.list()
                all_models = [model.id for model in models_response.data]
                
                # Sort models with newest first (based on date in model name)
                all_models = sorted(all_models, reverse=True)
                
                if all_models:
                    MODEL_OPTIONS[provider] = all_models
                    print(f"✓ Loaded {len(MODEL_OPTIONS[provider])} models for {provider}")
                else:
                    # Fallback to basic list if no models returned
                    MODEL_OPTIONS[provider] = ["claude-3-haiku-20240307"]
                    print(f"⚠ No models returned for {provider}, using fallback")
                
            elif config["type"] == "openrouter":
                # OpenRouter uses OpenAI-compatible API
                client = OpenAI(
                    api_key=api_key,
                    base_url=config["base_url"]
                )
                
                # List available models from OpenRouter
                models_response = client.models.list()
                all_models = [model.id for model in models_response.data]
                
                # Filter for DeepSeek models on OpenRouter
                if provider == "deepseek":
                    models = [m for m in all_models if "deepseek" in m.lower()]
                else:
                    models = all_models
                
                # If no models match filter, show warning with available models
                if not models:
                    print(f"⚠ Warning: No models matched filter for {provider}")
                    print(f"  Available models: {', '.join(all_models[:5])}{'...' if len(all_models) > 5 else ''}")
                    models = all_models  # Use all models as fallback
                
                MODEL_OPTIONS[provider] = sorted(models, reverse=True) if models else models
                print(f"✓ Loaded {len(MODEL_OPTIONS[provider])} models for {provider}")
                
            elif config["type"] == "google":
                from google import genai

                client = genai.Client(api_key=api_key)
                models_page = client.models.list()
                all_models = [
                    m.name.replace("models/", "") if m.name.startswith("models/") else m.name
                    for m in models_page
                ]
                models = [m for m in all_models if "gemini" in m.lower()]

                if not models:
                    print(f"⚠ Warning: No Gemini models found for {provider}")
                    print(f"  Available models: {', '.join(all_models[:5])}{'...' if len(all_models) > 5 else ''}")
                    models = all_models

                MODEL_OPTIONS[provider] = sorted(models, reverse=True) if models else models
                print(f"✓ Loaded {len(MODEL_OPTIONS[provider])} models for {provider}")

            elif config["type"] == "ollama":
                # Ollama exposes an OpenAI-compatible API
                import httpx
                ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
                client = OpenAI(
                    api_key="ollama",
                    base_url=f"{ollama_host}/v1",
                    timeout=httpx.Timeout(5.0, connect=5.0),
                )

                models_response = client.models.list()
                all_models = [model.id for model in models_response.data]

                MODEL_OPTIONS[provider] = sorted(all_models, reverse=True) if all_models else all_models
                print(f"✓ Loaded {len(MODEL_OPTIONS[provider])} models for {provider}")

            elif config["type"] == "vllm":
                # vLLM exposes an OpenAI-compatible API at /v1
                import httpx
                vllm_base = os.getenv("VLLM_BASE_URL", "http://localhost:8000").rstrip("/")
                if not vllm_base.endswith("/v1"):
                    vllm_base = f"{vllm_base}/v1"
                client = OpenAI(
                    api_key=api_key,
                    base_url=vllm_base,
                    timeout=httpx.Timeout(5.0, connect=5.0),
                )

                models_response = client.models.list()
                all_models = [model.id for model in models_response.data]

                MODEL_OPTIONS[provider] = sorted(all_models, reverse=True) if all_models else all_models
                print(f"✓ Loaded {len(MODEL_OPTIONS[provider])} models for {provider}")

            elif config["type"] == "azure":
                # Azure uses deployment names (not base model names) for API calls.
                # Read from AZURE_OPENAI_DEPLOYMENT env var (comma-separated).
                azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "")
                deployment_csv = os.getenv("AZURE_OPENAI_DEPLOYMENT", "")
                if not azure_endpoint:
                    print(f"⚠ Warning: AZURE_OPENAI_ENDPOINT not set, skipping {provider}")
                    continue
                if deployment_csv:
                    MODEL_OPTIONS[provider] = [d.strip() for d in deployment_csv.split(",") if d.strip()]
                    print(f"✓ Loaded {len(MODEL_OPTIONS[provider])} deployments for {provider}")

            else:  # openai (OpenAI-compatible provider)
                client_args = {"api_key": api_key}
                if config["base_url"]:
                    client_args["base_url"] = config["base_url"]

                client = OpenAI(**client_args)

                # List available models
                models_response = client.models.list()
                all_models = [model.id for model in models_response.data]

                # Filter for GPT models (including o1, o3 series)
                models = [m for m in all_models if any(keyword in m.lower() for keyword in ["gpt-4", "gpt-3.5", "gpt-4o", "o1", "o3"])]

                if not models:
                    print(f"⚠ Warning: No models matched filter for {provider}")
                    print(f"  Available models: {', '.join(all_models[:5])}{'...' if len(all_models) > 5 else ''}")
                    models = all_models

                MODEL_OPTIONS[provider] = sorted(models, reverse=True) if models else models
                print(f"✓ Loaded {len(MODEL_OPTIONS[provider])} models for {provider}")
                
        except Exception as e:
            error_msg = str(e)
            print(f"✗ Error loading models for {provider}: {error_msg}")
            
            # Special handling for API key errors
            if "401" in error_msg or "invalid_api_key" in error_msg.lower():
                print(f"  → API key issue detected. Please verify {config['api_key_env']} in .env file")
                print(f"  → Key starts with: {api_key[:10]}... (length: {len(api_key)})")
            elif "connection" in error_msg.lower():
                print(f"  → Network connection issue. Check internet connectivity or proxy settings")
            
            # Fallback to predefined list
            fallback_models = {
                "google": ["gemini-2.0-flash-exp", "gemini-2.5-flash", "gemini-1.5-pro", "gemini-1.5-flash"],
                "openai": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
                "deepseek": ["deepseek-chat", "deepseek-reasoner"],
                "azure": [os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")],
            }
            if provider in fallback_models:
                MODEL_OPTIONS[provider] = fallback_models[provider]
                print(f"  → Using fallback models for {provider}")
    
    return MODEL_OPTIONS


def to_timestamp_safe(col, format_str: str):
    """
    Safely convert a column to timestamp type, handling various date/time formats.
    Returns NULL (NaT) for unparseable values instead of failing.
    
    Args:
        col: PySpark column to convert
        format_str (str): The date/time format string (e.g., "MM/dd/yyyy HH:mm:ss")
    
    Returns:
        PySpark Column: Converted timestamp column with NULL for unparseable values
    """
    from pyspark.sql.functions import to_timestamp, coalesce, lit, when, col as F_col, isnan, isnull, try_to_timestamp
    
    # Try using try_to_timestamp if available (Spark 3.3+), otherwise use to_timestamp with coalesce
    try:
        # Try using try_to_timestamp which returns NULL for invalid values
        return try_to_timestamp(col, format_str)
    except:
        # Fallback for older Spark versions: try multiple common formats
        formats = [
            format_str,
            "yyyy-MM-dd HH:mm:ss",
            "yyyy-MM-dd",
            "MM/dd/yyyy",
            "dd-MM-yyyy",
            "yyyy/MM/dd",
        ]
        
        result = None
        for fmt in formats:
            try:
                attempt = to_timestamp(col, fmt)
                if result is None:
                    result = attempt
                else:
                    result = coalesce(result, attempt)
            except:
                continue
        
        # If all formats fail, return null
        return coalesce(result, lit(None).cast("timestamp"))
    

def generate_table_descriptions(spark, list_of_tables, llm_provider, model, api_key=None, temperature=0.5):
    """
    Generate descriptions for tables using an LLM by analyzing sample data.
    
    Args:
        spark: SparkSession object
        list_of_tables (list): List of table names
        llm_provider (str): LLM provider - "google", "anthropic", "openai", or "deepseek"
        model (str): The model ID to use
        api_key (str): API key for the provider. If None, uses provider-specific env var
        temperature (float): Temperature for model generation (default: 0.5)
    
    Returns:
        list: List of dictionaries with FILE_NAME and DESCRIPTION
    """
    import os
    
    table_descriptions = []
    
    for table_name in list_of_tables:
        try:
            # Strip file extensions from table name (e.g., .csv, .parquet)
            clean_table_name = table_name.replace('.csv', '').replace('.parquet', '').replace('.txt', '').replace('.xlsx', '')
            
            # Read the table and get random 10 rows as sample
            df = spark.table(clean_table_name)
            sample_df = df.limit(10)
            
            # Get column names and sample data as string
            columns = df.columns
            sample_data = sample_df.toPandas().to_string(index=False)
            
            columns_list = ", ".join(columns)
            
            prompt = f"""
Based on the table name '{clean_table_name}', its columns: {columns_list}

And sample data (first 10 rows):
{sample_data}

Please provide a concise description of what this table contains and its purpose in less than 50 words.
Focus on what kind of data it stores and its role in the overall data model.
"""
            
            # Provider-specific environment variable names
            env_var_map = {
                "google": "GOOGLE_API_KEY",
                "anthropic": "ANTHROPIC_API_KEY",
                "openai": "OPENAI_API_KEY",
                "deepseek": "OPENROUTER_API_KEY",
                "azure": "AZURE_OPENAI_API_KEY",
            }

            # Get API key
            if api_key is None:
                api_key = os.getenv(env_var_map.get(llm_provider.lower()))
                if not api_key:
                    description = f"API key not found for {clean_table_name}"
                    table_descriptions.append({
                        "TABLE_NAME": clean_table_name,
                        "DESCRIPTION": description
                    })
                    continue

            if llm_provider.lower() == "anthropic":
                from anthropic import Anthropic

                client = Anthropic(api_key=api_key)
                response = client.messages.create(
                    model=model,
                    max_tokens=300,
                    temperature=temperature,
                    messages=[
                        {"role": "user", "content": prompt}
                    ]
                )
                description = response.content[0].text.strip()

            elif llm_provider.lower() == "google":
                from google import genai

                client = genai.Client(api_key=api_key)
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=genai.types.GenerateContentConfig(
                        temperature=temperature,
                        max_output_tokens=300,
                    ),
                )
                description = response.text.strip()

            elif llm_provider.lower() == "azure":
                from openai import AzureOpenAI

                client = AzureOpenAI(
                    api_key=api_key,
                    api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
                    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT", ""),
                )
                deployment = model or os.getenv("AZURE_OPENAI_DEPLOYMENT", "")
                response = client.chat.completions.create(
                    model=deployment,
                    messages=[{"role": "user", "content": prompt}],
                    max_completion_tokens=300,
                )
                description = response.choices[0].message.content.strip()

            else:  # openai, deepseek (OpenAI-compatible providers)
                from openai import OpenAI

                base_url_map = {
                    "openai": None,
                    "deepseek": "https://openrouter.ai/api/v1",
                }

                client_args = {"api_key": api_key}
                if base_url_map.get(llm_provider.lower()) is not None:
                    client_args["base_url"] = base_url_map[llm_provider.lower()]

                client = OpenAI(**client_args)

                response = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "user", "content": prompt},
                    ],
                    temperature=temperature,
                    max_tokens=300,
                )
                description = response.choices[0].message.content.strip()
            
            table_descriptions.append({
                "TABLE_NAME": clean_table_name,
                "TABLE_DESCRIPTION": description
            })
            
        except Exception as e:
            print(f"  ❌ Error generating description for table {clean_table_name}: {str(e)}")
            table_descriptions.append({
                "TABLE_NAME": clean_table_name,
                "DESCRIPTION": f"Error generating description for {clean_table_name}"
            })
    
    return table_descriptions


def generate_entity_relationships(spark, metadata_json, llm_provider, model, api_key=None, temperature=0.5):
    """
    Generate entity relationships between tables using an LLM.
    
    Args:
        spark: SparkSession object
        metadata_json (str): JSON string containing table metadata
        llm_provider (str): LLM provider - "google", "anthropic", "openai", or "deepseek"
        model (str): The model ID to use
        api_key (str): API key for the provider. If None, uses provider-specific env var
        temperature (float): Temperature for model generation (default: 0.5)
    
    Returns:
        list: List of dictionaries with relationship information
    """
    import os
    import ast
    
    prompt = f"""
Based on the following table metadata (columns and their descriptions):

{metadata_json}

Please identify all potential relationships between tables. Look for:
- Foreign key relationships (e.g., ID columns that reference other tables)
- Common columns that link tables together
- Naming patterns that suggest relationships (e.g., Company_ID, Scientific_Expert_ID)

Return ONLY a JSON array of objects with this exact format (no additional text):
[
  {{"TABLE_NAME": "table1", "COLUMN_NAME": "column1", "RELATED_TABLE_NAME": "table2", "RELATED_COLUMN_NAME": "column2"}},
  {{"TABLE_NAME": "table1", "COLUMN_NAME": "column3", "RELATED_TABLE_NAME": "table3", "RELATED_COLUMN_NAME": "column4"}}
]

IMPORTANT: Use table names WITHOUT file extensions (e.g., use 'address_20260115' not 'address_20260115.csv').

Only include high-confidence relationships. If no relationships found, return an empty array [].
"""
    
    try:
        # Provider-specific environment variable names
        env_var_map = {
            "google": "GOOGLE_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "deepseek": "OPENROUTER_API_KEY",
            "azure": "AZURE_OPENAI_API_KEY",
        }

        # Get API key
        if api_key is None:
            api_key = os.getenv(env_var_map.get(llm_provider.lower()))
            if not api_key:
                print("  ❌ API key not found for relationship generation")
                return []

        if llm_provider.lower() == "anthropic":
            from anthropic import Anthropic

            client = Anthropic(api_key=api_key)
            response = client.messages.create(
                model=model,
                max_tokens=8000,
                temperature=temperature,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            content = response.content[0].text.strip()

        elif llm_provider.lower() == "google":
            from google import genai

            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=genai.types.GenerateContentConfig(
                    temperature=temperature,
                    max_output_tokens=8000,
                ),
            )
            content = response.text.strip()

        elif llm_provider.lower() == "azure":
            from openai import AzureOpenAI

            client = AzureOpenAI(
                api_key=api_key,
                api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
                azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT", ""),
            )
            deployment = model or os.getenv("AZURE_OPENAI_DEPLOYMENT", "")
            response = client.chat.completions.create(
                model=deployment,
                messages=[{"role": "user", "content": prompt}],
                max_completion_tokens=8000,
            )
            content = response.choices[0].message.content.strip()

        else:  # openai, deepseek (OpenAI-compatible providers)
            from openai import OpenAI

            base_url_map = {
                "openai": None,
                "deepseek": "https://openrouter.ai/api/v1",
            }

            client_args = {"api_key": api_key}
            if base_url_map.get(llm_provider.lower()) is not None:
                client_args["base_url"] = base_url_map[llm_provider.lower()]

            client = OpenAI(**client_args)

            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "user", "content": prompt},
                ],
                temperature=temperature,
                max_tokens=8000,
            )
            content = response.choices[0].message.content.strip()
        
        # Extract JSON from response (handle markdown code blocks)
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        
        # Parse JSON response
        relationships = ast.literal_eval(content)
        return relationships if isinstance(relationships, list) else []
        
    except Exception as e:
        print(f"  ❌ Error generating relationships: {str(e)}")
        return []
    
def generate_column_description(spark, table_name, column_name, sample_values, llm_provider, model, api_key=None, temperature=0.5):
    """
    Generate a description for a column using an LLM.
    
    Args:
        spark: SparkSession object
        table_name (str): Name of the table
        column_name (str): Name of the column
        sample_values (list): List of sample values from the column
        llm_provider (str): LLM provider - "google", "anthropic", "openai", or "deepseek"
        model (str): The model ID to use
        api_key (str): API key for the provider. If None, uses provider-specific env var
        temperature (float): Temperature for model generation (default: 0.5)
    
    Returns:
        str: Generated column description
    """
    import os
    
    # Prepare the prompt
    sample_str = ", ".join([str(val) for val in sample_values[:10]])  # Limit to 10 values
    
    prompt = f"""
Based on these sample values from the column '{column_name}' in the table '{table_name}':
{sample_str}

Please provide a concise description of what this column contains in less than 40 words.
Focus on the type of data, its purpose, and any patterns you observe.
"""
    
    try:
        # Provider-specific environment variable names
        env_var_map = {
            "google": "GOOGLE_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "deepseek": "OPENROUTER_API_KEY",
            "azure": "AZURE_OPENAI_API_KEY",
        }

        # Get API key
        if api_key is None:
            api_key = os.getenv(env_var_map.get(llm_provider.lower()))
            if not api_key:
                return f"API key not found for {column_name}"

        if llm_provider.lower() == "anthropic":
            from anthropic import Anthropic

            client = Anthropic(api_key=api_key)
            response = client.messages.create(
                model=model,
                max_tokens=200,
                temperature=temperature,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            description = response.content[0].text.strip()

        elif llm_provider.lower() == "google":
            from google import genai

            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=genai.types.GenerateContentConfig(
                    temperature=temperature,
                    max_output_tokens=200,
                ),
            )
            description = response.text.strip()

        elif llm_provider.lower() == "azure":
            from openai import AzureOpenAI

            client = AzureOpenAI(
                api_key=api_key,
                api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
                azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT", ""),
            )
            deployment = model or os.getenv("AZURE_OPENAI_DEPLOYMENT", "")
            response = client.chat.completions.create(
                model=deployment,
                messages=[{"role": "user", "content": prompt}],
                max_completion_tokens=200,
            )
            description = response.choices[0].message.content.strip()

        else:  # openai, deepseek (OpenAI-compatible providers)
            from openai import OpenAI

            base_url_map = {
                "openai": None,
                "deepseek": "https://openrouter.ai/api/v1",
            }

            client_args = {"api_key": api_key}
            if base_url_map.get(llm_provider.lower()) is not None:
                client_args["base_url"] = base_url_map[llm_provider.lower()]

            client = OpenAI(**client_args)

            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "user", "content": prompt},
                ],
                temperature=temperature,
                max_tokens=200,
            )
            description = response.choices[0].message.content.strip()
        
        return description
        
    except Exception as e:
        print(f"  ❌ Error generating description for {column_name}: {str(e)}")
        return f"Error generating description for {column_name}"