import os
import shutil
import streamlit

# Locate the installed streamlit static folder
streamlit_static_path = os.path.join(streamlit.__path__[0], "static")
cwd = os.getcwd()

print(f"Streamlit static folder found at: {streamlit_static_path}")

# 1. Copy PWA files to streamlit static directory
shutil.copy("manifest.json", streamlit_static_path)
shutil.copy("sw.js", streamlit_static_path)

# Copy icons folder
dest_icons_dir = os.path.join(streamlit_static_path, "icons")
if os.path.exists(dest_icons_dir):
    shutil.rmtree(dest_icons_dir)
shutil.copytree("icons", dest_icons_dir)

print("PWA assets copied to Streamlit server.")

# 2. Modify Streamlit's default index.html to insert PWA tags
index_html_path = os.path.join(streamlit_static_path, "index.html")
with open(index_html_path, "r", encoding="utf-8") as f:
    html = f.read()

# Check if already patched to prevent duplicate injections
if "manifest.json" not in html:
    # Inject PWA links into <head>
    pwa_head_tags = """
    <link rel="manifest" href="manifest.json">
    <link rel="icon" type="image/png" sizes="192x192" href="icons/icon-192.png">
    <link rel="icon" type="image/png" sizes="512x512" href="icons/icon-512.png">
    <link rel="apple-touch-icon" href="icons/icon-192.png">
    <meta name="mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    """
    html = html.replace("<head>", "<head>" + pwa_head_tags)
    
    # Inject service worker registration script before </body>
    sw_script = """
    <script>
        if ('serviceWorker' in navigator) {
            navigator.serviceWorker.register('sw.js')
                .then(reg => console.log('Service Worker Registered!'))
                .catch(err => console.log('Service Worker Registration Failed!', err));
        }
    </script>
    </body>
    """
    html = html.replace("</body>", sw_script)
    
    with open(index_html_path, "w", encoding="utf-8") as f:
        f.write(html)
    print("Streamlit index.html patched for PWA successfully!")
else:
    print("Streamlit index.html already patched.")
