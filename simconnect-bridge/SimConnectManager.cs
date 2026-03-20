using System.Runtime.InteropServices;
using Microsoft.FlightSimulator.SimConnect;
using SimConnectBridge.Models;

namespace SimConnectBridge;

/// <summary>
/// Manages the SimConnect connection lifecycle, data definition registration,
/// periodic polling, and state updates.
/// </summary>
public sealed class SimConnectManager : IDisposable
{
    private SimConnect? _simConnect;
    private readonly string _appName;
    private readonly int _highFrequencyHz;
    private readonly int _lowFrequencyHz;
    private readonly object _lock = new();

    private Timer? _highFreqTimer;
    private Timer? _lowFreqTimer;
    private Timer? _messageTimer;
    private bool _connected;
    private bool _disposed;

    /// <summary>
    /// The current simulation state, updated on each data receive callback.
    /// </summary>
    public SimState CurrentState { get; } = new();

    /// <summary>
    /// Raised whenever the sim state is updated with new telemetry data.
    /// </summary>
    public event Action<SimState>? StateUpdated;

    /// <summary>
    /// Raised when the SimConnect connection status changes.
    /// </summary>
    public event Action<bool>? ConnectionChanged;

    /// <summary>
    /// Creates a new <see cref="SimConnectManager"/> with the given configuration.
    /// </summary>
    /// <param name="appName">Application name registered with SimConnect.</param>
    /// <param name="highFrequencyHz">Poll rate for position/attitude/speed data.</param>
    /// <param name="lowFrequencyHz">Poll rate for fuel/environment/autopilot data.</param>
    public SimConnectManager(string appName, int highFrequencyHz = 30, int lowFrequencyHz = 1)
    {
        _appName = appName;
        _highFrequencyHz = highFrequencyHz;
        _lowFrequencyHz = lowFrequencyHz;
    }

    /// <summary>
    /// Attempts to open a connection to MSFS via SimConnect.
    /// Starts polling timers on success.
    /// </summary>
    /// <returns>True if the connection was established; false otherwise.</returns>
    public bool Connect()
    {
        try
        {
            _simConnect = new SimConnect(_appName, IntPtr.Zero, 0, null, 0);

            _simConnect.OnRecvOpen += OnRecvOpen;
            _simConnect.OnRecvQuit += OnRecvQuit;
            _simConnect.OnRecvException += OnRecvException;
            _simConnect.OnRecvSimobjectData += OnRecvSimobjectData;

            RegisterDataDefinitions();

            // Start a timer to pump SimConnect messages (required for out-of-process)
            _messageTimer = new Timer(
                _ => ReceiveMessages(),
                null,
                TimeSpan.Zero,
                TimeSpan.FromMilliseconds(10));

            _connected = true;
            CurrentState.Connected = true;
            ConnectionChanged?.Invoke(true);

            Console.WriteLine("[SimConnect] Connection opened.");
            return true;
        }
        catch (COMException ex)
        {
            Console.WriteLine($"[SimConnect] Failed to connect: {ex.Message}");
            _connected = false;
            CurrentState.Connected = false;
            return false;
        }
    }

    /// <summary>
    /// Attempts to connect to SimConnect in a retry loop until cancelled.
    /// </summary>
    /// <param name="cancellationToken">Token to cancel the retry loop.</param>
    /// <param name="retryDelayMs">Delay between connection attempts.</param>
    public async Task ConnectWithRetryAsync(CancellationToken cancellationToken, int retryDelayMs = 5000)
    {
        while (!cancellationToken.IsCancellationRequested)
        {
            if (Connect())
                return;

            Console.WriteLine($"[SimConnect] Retrying in {retryDelayMs}ms...");
            await Task.Delay(retryDelayMs, cancellationToken).ConfigureAwait(false);
        }
    }

    /// <summary>
    /// Disconnects from SimConnect and stops all polling timers.
    /// </summary>
    public void Disconnect()
    {
        StopTimers();

        if (_simConnect is not null)
        {
            try
            {
                _simConnect.Dispose();
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[SimConnect] Error during disconnect: {ex.Message}");
            }
            _simConnect = null;
        }

        _connected = false;
        CurrentState.Connected = false;
        ConnectionChanged?.Invoke(false);
        Console.WriteLine("[SimConnect] Disconnected.");
    }

    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        Disconnect();
    }

    // -----------------------------------------------------------------------
    //  Data Definition Registration
    // -----------------------------------------------------------------------

    private void RegisterDataDefinitions()
    {
        if (_simConnect is null) return;

        // -- High-frequency data (position, attitude, speeds) --
        var hf = DataDefinitionId.HighFrequency;
        AddFloat64(_simConnect, hf, "PLANE LATITUDE", "degrees");
        AddFloat64(_simConnect, hf, "PLANE LONGITUDE", "degrees");
        AddFloat64(_simConnect, hf, "PLANE ALTITUDE", "feet");
        AddFloat64(_simConnect, hf, "PLANE ALT ABOVE GROUND", "feet");
        AddFloat64(_simConnect, hf, "PLANE PITCH DEGREES", "degrees");
        AddFloat64(_simConnect, hf, "PLANE BANK DEGREES", "degrees");
        AddFloat64(_simConnect, hf, "PLANE HEADING DEGREES TRUE", "degrees");
        AddFloat64(_simConnect, hf, "PLANE HEADING DEGREES MAGNETIC", "degrees");
        AddFloat64(_simConnect, hf, "AIRSPEED INDICATED", "knots");
        AddFloat64(_simConnect, hf, "AIRSPEED TRUE", "knots");
        AddFloat64(_simConnect, hf, "GROUND VELOCITY", "knots");
        AddFloat64(_simConnect, hf, "AIRSPEED MACH", "mach");
        AddFloat64(_simConnect, hf, "VERTICAL SPEED", "feet per minute");

        // -- Low-frequency data (autopilot, radios, fuel, surfaces, environment) --
        var lf = DataDefinitionId.LowFrequency;
        AddInt32(_simConnect, lf, "AUTOPILOT MASTER", "bool");
        AddFloat64(_simConnect, lf, "AUTOPILOT HEADING LOCK DIR", "degrees");
        AddFloat64(_simConnect, lf, "AUTOPILOT ALTITUDE LOCK VAR", "feet");
        AddFloat64(_simConnect, lf, "AUTOPILOT VERTICAL HOLD VAR", "feet per minute");
        AddFloat64(_simConnect, lf, "AUTOPILOT AIRSPEED HOLD VAR", "knots");
        AddFloat64(_simConnect, lf, "COM ACTIVE FREQUENCY:1", "MHz");
        AddFloat64(_simConnect, lf, "COM ACTIVE FREQUENCY:2", "MHz");
        AddFloat64(_simConnect, lf, "NAV ACTIVE FREQUENCY:1", "MHz");
        AddFloat64(_simConnect, lf, "NAV ACTIVE FREQUENCY:2", "MHz");
        AddFloat64(_simConnect, lf, "FUEL TOTAL QUANTITY", "gallons");
        AddFloat64(_simConnect, lf, "FUEL TOTAL QUANTITY WEIGHT", "pounds");
        AddInt32(_simConnect, lf, "GEAR HANDLE POSITION", "bool");
        AddFloat64(_simConnect, lf, "TRAILING EDGE FLAPS LEFT PERCENT", "percent");
        AddFloat64(_simConnect, lf, "SPOILERS HANDLE POSITION", "percent");
        AddFloat64(_simConnect, lf, "AMBIENT WIND VELOCITY", "knots");
        AddFloat64(_simConnect, lf, "AMBIENT WIND DIRECTION", "degrees");
        AddFloat64(_simConnect, lf, "AMBIENT VISIBILITY", "statute miles");
        AddFloat64(_simConnect, lf, "AMBIENT TEMPERATURE", "celsius");
        AddFloat64(_simConnect, lf, "BAROMETER PRESSURE", "inches of mercury");

        // -- Engine data (4 engines x 6 params) --
        var eng = DataDefinitionId.EngineData;
        for (int i = 1; i <= 4; i++)
        {
            AddFloat64(_simConnect, eng, $"GENERAL ENG RPM:{i}", "rpm");
            AddFloat64(_simConnect, eng, $"ENG MANIFOLD PRESSURE:{i}", "inHg");
            AddFloat64(_simConnect, eng, $"ENG FUEL FLOW GPH:{i}", "gallons per hour");
            AddFloat64(_simConnect, eng, $"ENG EXHAUST GAS TEMPERATURE:{i}", "rankine");
            AddFloat64(_simConnect, eng, $"ENG OIL TEMPERATURE:{i}", "rankine");
            AddFloat64(_simConnect, eng, $"ENG OIL PRESSURE:{i}", "psf");
        }

        // -- Aircraft title (string) --
        _simConnect.AddToDataDefinition(
            DataDefinitionId.AircraftTitle,
            "TITLE",
            null,
            SIMCONNECT_DATATYPE.STRING256,
            0.0f,
            SimConnect.SIMCONNECT_UNUSED);

        // Register struct mappings
        _simConnect.RegisterDataDefineStruct<HighFrequencyData>(DataDefinitionId.HighFrequency);
        _simConnect.RegisterDataDefineStruct<LowFrequencyData>(DataDefinitionId.LowFrequency);
        _simConnect.RegisterDataDefineStruct<EngineDataStruct>(DataDefinitionId.EngineData);
        _simConnect.RegisterDataDefineStruct<AircraftTitleData>(DataDefinitionId.AircraftTitle);

        Console.WriteLine("[SimConnect] Data definitions registered.");
    }

    private static void AddFloat64(SimConnect sc, DataDefinitionId defId, string varName, string units)
    {
        sc.AddToDataDefinition(defId, varName, units,
            SIMCONNECT_DATATYPE.FLOAT64, 0.0f, SimConnect.SIMCONNECT_UNUSED);
    }

    private static void AddInt32(SimConnect sc, DataDefinitionId defId, string varName, string units)
    {
        sc.AddToDataDefinition(defId, varName, units,
            SIMCONNECT_DATATYPE.INT32, 0.0f, SimConnect.SIMCONNECT_UNUSED);
    }

    // -----------------------------------------------------------------------
    //  Polling Timers
    // -----------------------------------------------------------------------

    private void StartPolling()
    {
        int highFreqMs = _highFrequencyHz > 0 ? 1000 / _highFrequencyHz : 33;
        int lowFreqMs = _lowFrequencyHz > 0 ? 1000 / _lowFrequencyHz : 1000;

        _highFreqTimer = new Timer(_ => RequestHighFrequencyData(), null,
            TimeSpan.Zero, TimeSpan.FromMilliseconds(highFreqMs));

        _lowFreqTimer = new Timer(_ => RequestLowFrequencyData(), null,
            TimeSpan.Zero, TimeSpan.FromMilliseconds(lowFreqMs));

        Console.WriteLine($"[SimConnect] Polling started: high-freq={_highFrequencyHz}Hz, low-freq={_lowFrequencyHz}Hz");
    }

    private void StopTimers()
    {
        _highFreqTimer?.Dispose();
        _highFreqTimer = null;
        _lowFreqTimer?.Dispose();
        _lowFreqTimer = null;
        _messageTimer?.Dispose();
        _messageTimer = null;
    }

    private void RequestHighFrequencyData()
    {
        try
        {
            _simConnect?.RequestDataOnSimObject(
                DataRequestId.HighFrequency,
                DataDefinitionId.HighFrequency,
                SimConnect.SIMCONNECT_OBJECT_ID_USER,
                SIMCONNECT_PERIOD.ONCE,
                SIMCONNECT_DATA_REQUEST_FLAG.DEFAULT,
                0, 0, 0);
        }
        catch (COMException)
        {
            HandleDisconnect();
        }
    }

    private void RequestLowFrequencyData()
    {
        try
        {
            _simConnect?.RequestDataOnSimObject(
                DataRequestId.LowFrequency,
                DataDefinitionId.LowFrequency,
                SimConnect.SIMCONNECT_OBJECT_ID_USER,
                SIMCONNECT_PERIOD.ONCE,
                SIMCONNECT_DATA_REQUEST_FLAG.DEFAULT,
                0, 0, 0);

            _simConnect?.RequestDataOnSimObject(
                DataRequestId.EngineData,
                DataDefinitionId.EngineData,
                SimConnect.SIMCONNECT_OBJECT_ID_USER,
                SIMCONNECT_PERIOD.ONCE,
                SIMCONNECT_DATA_REQUEST_FLAG.DEFAULT,
                0, 0, 0);

            _simConnect?.RequestDataOnSimObject(
                DataRequestId.AircraftTitle,
                DataDefinitionId.AircraftTitle,
                SimConnect.SIMCONNECT_OBJECT_ID_USER,
                SIMCONNECT_PERIOD.ONCE,
                SIMCONNECT_DATA_REQUEST_FLAG.DEFAULT,
                0, 0, 0);
        }
        catch (COMException)
        {
            HandleDisconnect();
        }
    }

    // -----------------------------------------------------------------------
    //  Message pump (required for out-of-process SimConnect)
    // -----------------------------------------------------------------------

    private void ReceiveMessages()
    {
        try
        {
            _simConnect?.ReceiveMessage();
        }
        catch (COMException)
        {
            HandleDisconnect();
        }
    }

    // -----------------------------------------------------------------------
    //  SimConnect Callbacks
    // -----------------------------------------------------------------------

    private void OnRecvOpen(SimConnect sender, SIMCONNECT_RECV_OPEN data)
    {
        Console.WriteLine($"[SimConnect] Recv Open: {data.szApplicationName}");
        StartPolling();
    }

    private void OnRecvQuit(SimConnect sender, SIMCONNECT_RECV data)
    {
        Console.WriteLine("[SimConnect] Simulator quit.");
        HandleDisconnect();
    }

    private void OnRecvException(SimConnect sender, SIMCONNECT_RECV_EXCEPTION data)
    {
        Console.WriteLine($"[SimConnect] Exception: {(SIMCONNECT_EXCEPTION)data.dwException} (SendID={data.dwSendID}, Index={data.dwIndex})");
    }

    /// <summary>
    /// Handles incoming sim object data and updates the current state.
    /// </summary>
    private void OnRecvSimobjectData(SimConnect sender, SIMCONNECT_RECV_SIMOBJECT_DATA data)
    {
        lock (_lock)
        {
            switch ((DataRequestId)data.dwRequestID)
            {
                case DataRequestId.HighFrequency:
                    ApplyHighFrequencyData((HighFrequencyData)data.dwData[0]);
                    break;

                case DataRequestId.LowFrequency:
                    ApplyLowFrequencyData((LowFrequencyData)data.dwData[0]);
                    break;

                case DataRequestId.EngineData:
                    ApplyEngineData((EngineDataStruct)data.dwData[0]);
                    break;

                case DataRequestId.AircraftTitle:
                    var titleData = (AircraftTitleData)data.dwData[0];
                    CurrentState.Aircraft = titleData.Title ?? string.Empty;
                    break;
            }

            CurrentState.Timestamp = DateTimeOffset.UtcNow;
        }

        StateUpdated?.Invoke(CurrentState);
    }

    private void ApplyHighFrequencyData(HighFrequencyData d)
    {
        CurrentState.Position.Latitude = d.PlaneLatitude;
        CurrentState.Position.Longitude = d.PlaneLongitude;
        CurrentState.Position.AltitudeMsl = d.PlaneAltitude;
        CurrentState.Position.AltitudeAgl = d.PlaneAltAboveGround;

        CurrentState.Attitude.Pitch = d.PlanePitchDegrees;
        CurrentState.Attitude.Bank = d.PlaneBankDegrees;
        CurrentState.Attitude.HeadingTrue = d.PlaneHeadingTrue;
        CurrentState.Attitude.HeadingMagnetic = d.PlaneHeadingMagnetic;

        CurrentState.Speeds.IndicatedAirspeed = d.AirspeedIndicated;
        CurrentState.Speeds.TrueAirspeed = d.AirspeedTrue;
        CurrentState.Speeds.GroundSpeed = d.GroundVelocity;
        CurrentState.Speeds.Mach = d.AirspeedMach;
        CurrentState.Speeds.VerticalSpeed = d.VerticalSpeed;
    }

    private void ApplyLowFrequencyData(LowFrequencyData d)
    {
        CurrentState.Autopilot.Master = d.AutopilotMaster != 0;
        CurrentState.Autopilot.Heading = d.AutopilotHeading;
        CurrentState.Autopilot.Altitude = d.AutopilotAltitude;
        CurrentState.Autopilot.VerticalSpeed = d.AutopilotVerticalSpeed;
        CurrentState.Autopilot.Airspeed = d.AutopilotAirspeed;

        CurrentState.Radios.Com1 = d.Com1Frequency;
        CurrentState.Radios.Com2 = d.Com2Frequency;
        CurrentState.Radios.Nav1 = d.Nav1Frequency;
        CurrentState.Radios.Nav2 = d.Nav2Frequency;

        CurrentState.Fuel.TotalGallons = d.FuelTotalQuantity;
        CurrentState.Fuel.TotalWeightLbs = d.FuelTotalWeight;

        CurrentState.Surfaces.GearHandle = d.GearHandlePosition != 0;
        CurrentState.Surfaces.FlapsPercent = d.FlapsPercent;
        CurrentState.Surfaces.SpoilersPercent = d.SpoilersPercent;

        CurrentState.Environment.WindSpeedKts = d.WindVelocity;
        CurrentState.Environment.WindDirection = d.WindDirection;
        CurrentState.Environment.VisibilitySm = d.Visibility;
        CurrentState.Environment.TemperatureC = d.AmbientTemperature;
        CurrentState.Environment.BarometerInHg = d.BarometerPressure;
    }

    private void ApplyEngineData(EngineDataStruct d)
    {
        ApplyOneEngine(CurrentState.Engines.Engines[0],
            d.Eng1Rpm, d.Eng1ManifoldPressure, d.Eng1FuelFlow, d.Eng1Egt, d.Eng1OilTemp, d.Eng1OilPressure);
        ApplyOneEngine(CurrentState.Engines.Engines[1],
            d.Eng2Rpm, d.Eng2ManifoldPressure, d.Eng2FuelFlow, d.Eng2Egt, d.Eng2OilTemp, d.Eng2OilPressure);
        ApplyOneEngine(CurrentState.Engines.Engines[2],
            d.Eng3Rpm, d.Eng3ManifoldPressure, d.Eng3FuelFlow, d.Eng3Egt, d.Eng3OilTemp, d.Eng3OilPressure);
        ApplyOneEngine(CurrentState.Engines.Engines[3],
            d.Eng4Rpm, d.Eng4ManifoldPressure, d.Eng4FuelFlow, d.Eng4Egt, d.Eng4OilTemp, d.Eng4OilPressure);

        // Infer active engine count from RPM > 0
        int count = 0;
        for (int i = 0; i < 4; i++)
        {
            if (CurrentState.Engines.Engines[i].Rpm > 1.0)
                count = i + 1;
        }
        CurrentState.Engines.EngineCount = count;
    }

    private static void ApplyOneEngine(EngineParams ep,
        double rpm, double mp, double ff, double egt, double oilTemp, double oilPressure)
    {
        ep.Rpm = rpm;
        ep.ManifoldPressure = mp;
        ep.FuelFlowGph = ff;
        ep.ExhaustGasTemp = egt;
        ep.OilTemp = oilTemp;
        ep.OilPressure = oilPressure;
    }

    private void HandleDisconnect()
    {
        if (!_connected) return;
        _connected = false;
        CurrentState.Connected = false;
        StopTimers();
        ConnectionChanged?.Invoke(false);
        Console.WriteLine("[SimConnect] Connection lost.");
    }
}
