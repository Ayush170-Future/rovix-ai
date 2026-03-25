using UnityEngine;
using UnityEngine.Networking;
using System.Collections;
using System;
using System.Text;
using UnityEngine.Scripting; // Add this import

[Preserve] // Add this attribute to the class
public class frameController : MonoBehaviour
{
    private int currentStep = 0;
    private int lastEventStep = 0;
    private int eventInterval = 600;
    private bool eventSendEnabled = true;
    
    private string pythonServerUrl = "http://10.0.2.2:8000";
    
    // Make this public AND add [Preserve]
    [Preserve]
    public bool actionsExecuted = true;

    void Awake()
    {
        Application.runInBackground = true;
    }

    void Start()
    {
        DontDestroyOnLoad(gameObject);
        actionsExecuted = true;
        Debug.Log("[FrameController] Initialized - ready to send events");
        // Log the actual assembly name at runtime
        var assembly = this.GetType().Assembly;
        Debug.Log($"[FrameController] Runtime Assembly Name: {assembly.FullName}");
        Debug.Log($"[FrameController] Type Full Name: {this.GetType().FullName}");
        Debug.Log($"[FrameController] Assembly Location: {assembly.Location}");
        
        MarkActionsExecuted();
        int currentStep = GetCurrentStep();
        int currentFrame = GetCurrentFrame();
        Debug.Log($"[FrameController] Current Step: {currentStep}, Current Frame: {currentFrame}");
    }

    void FixedUpdate()
    {
        currentStep++;
        
        if (eventSendEnabled && currentStep - lastEventStep >= eventInterval && actionsExecuted)
        {
            SendEventToPython();
        }
    }

    private void SendEventToPython()
    {
        actionsExecuted = false;
        lastEventStep = currentStep;
        
        int currentFrame = Time.frameCount;
        
        string jsonPayload = $@"{{
            ""current_step"": {currentStep},
            ""current_frame"": {currentFrame}
        }}";
        
        Debug.Log($"[AI] Sending event to Python server at step {currentStep}, frame {currentFrame}");
        
        StartCoroutine(SendPostRequest(jsonPayload));
    }
    
    private IEnumerator SendPostRequest(string jsonData)
    {
        string url = $"{pythonServerUrl}/ai/on-pause";
        
        using (UnityWebRequest request = new UnityWebRequest(url, "POST"))
        {
            byte[] bodyRaw = Encoding.UTF8.GetBytes(jsonData);
            request.uploadHandler = new UploadHandlerRaw(bodyRaw);
            request.downloadHandler = new DownloadHandlerBuffer();
            request.SetRequestHeader("Content-Type", "application/json");
            request.certificateHandler = new AcceptAllCertificatesHandler();
            
            yield return request.SendWebRequest();
            
            if (request.result == UnityWebRequest.Result.Success)
            {
                Debug.Log($"[AI] ✅ Event sent successfully: {request.downloadHandler.text}");
            }
            else
            {
                Debug.LogError($"[AI] ❌ Event send failed: {request.error}");
                actionsExecuted = true;
            }
        }
    }
    
    private class AcceptAllCertificatesHandler : CertificateHandler
    {
        protected override bool ValidateCertificate(byte[] certificateData)
        {
            return true;
        }
    }
    
    /// <summary>
    /// Called by Python server via AltTester after actions are executed.
    /// </summary>
    [Preserve] // Add this to preserve the method
    public void MarkActionsExecuted()
    {
        actionsExecuted = true;
        Debug.Log($"[AI] Actions marked as executed at step {currentStep}, frame {Time.frameCount}");
    }
    
    [Preserve]
    public int GetCurrentStep()
    {
        return currentStep;
    }
    
    [Preserve]
    public int GetCurrentFrame()
    {
        return Time.frameCount;
    }
    
    [Preserve]
    public void SetEventInterval(int interval)
    {
        eventInterval = interval;
        Debug.Log($"[FrameController] Event interval set to {interval} steps");
    }
    
    [Preserve]
    public void EnableEventSend()
    {
        eventSendEnabled = true;
        Debug.Log("[FrameController] Event sending enabled");
    }
    
    [Preserve]
    public void DisableEventSend()
    {
        eventSendEnabled = false;
        Debug.Log("[FrameController] Event sending disabled - no events will be sent to Python");
    }
    
    [Preserve]
    public bool IsEventSendEnabled()
    {
        return eventSendEnabled;
    }
    
    [Preserve]
    public void PauseGame()
    {
        Time.timeScale = 0f;
        Debug.Log("[FrameController] Game paused (timeScale = 0)");
    }
    
    [Preserve]
    public void ResumeGame()
    {
        Time.timeScale = 1f;
        Debug.Log("[FrameController] Game resumed (timeScale = 1)");
    }
    
    [Preserve]
    public bool IsGamePaused()
    {
        return Time.timeScale == 0f;
    }
    
    [Preserve]
    public float GetTimeScale()
    {
        return Time.timeScale;
    }
    
    [Preserve]
    public void SetTimeScale(float scale)
    {
        Time.timeScale = scale;
        Debug.Log($"[FrameController] Time scale set to {scale}");
    }
    
    void OnDestroy()
    {
        Debug.Log("[FrameController] Destroyed");
    }
}