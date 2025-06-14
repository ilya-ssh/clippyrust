import logging

logging.basicConfig(
    filename='rust_tui_ide.log',
    filemode='w',
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
LLAMA_MODE = "local" #local/vpn                    
LLAMA_VPN_BASE_URL = "http://25.45.11.7:8000"  
LLAMA_LOCAL_URL = "http://127.0.0.1:1234"

LLM_NAME = "DeepSeek-R1-Distill-Qwen-14B-Q5_K_M.gguf"
#deprecated
LLAMA_SERVER_HOST = "http://localhost"
LLAMA_SERVER_PORT = "8000"
#
MODEL_PATH = "models/gemma-3-27b-it-q4_0.gguf"
CLIPPY_VERSION = ".alpha 0.0.4"
CLIPPY_ASCII = r"""


                                           .......                                            
                                         ...     ...                                          
                                       - .=:     --.=.                                        
                                      = .-         .+-                                        
                                     ...-           .*#                                       
                                     .:-             ::=                                      
                                     .=              :..                                      
                                .#@@#%@%#           =..+                                      
                             +%#*- = ::=*-.         =:                                        
                           ..      ...             .*--                                       
                                  . -.           .-###.                                       
                             .:.  ..#:         .  ---##%%#.                                   
                          ..   :--    .          =  =.    .%.                                 
                          .  .@@@@%%             :.. ..     -.                                 
                          ..   ==-=    .     ..   .    ..    .                                 
                            . .+-...:..     :  :#@=%@:  ..                                    
                               -@:          .  .#%@@@#  ..                                    
                              .@%.           =.      .                                        
                              .:=. ..         .%@@...-.                                       
                              %+. .#=.        -@+                                            
                              --. +.:        .##@                                            
                             * .  #+.         *@=                                            
                            ..=* ..#         =-:     =*%@%.                                  
                            +-.. - +         *.    .:@*+                                   
                            -. ...:-         ...  -:%.                                    
                           .#:. :-:.        .... - #.                                     
                           :+ + .  :        =     *=                                      
                           -* :  -. : ..  .= .: +*+                                       
                           :: -   ..   .    .. . #%                                       
                           =. *     ..:..:..   =+*#                                       
                           -: -                .: #                                       
                           =: +                :. :                                       
                           :+ -                -- .                                       
                           .*                 .#+ .                                       
                            +- -              :@#                                         
                             %+..             .#=:                                        
                              ==.-.           .*..                                        
                               -*. :.        :=:=                                         
                                .==. .:   ... .=.                                         
                                  ::..  ..    :                                           
                                    ...-:-...                                             


"""
